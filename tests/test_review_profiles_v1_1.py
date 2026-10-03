"""Profile compatibility in disposable storage; no real Reviewer quality claim."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from mcp import Client

from conftest import CONTRACTS, Flow
from grokbuddy.application.common import canonical, digest
from grokbuddy.application.trigger import PHRASE
from grokbuddy.domain.model import Conflict
from grokbuddy.infrastructure import profiles
from grokbuddy.infrastructure import runtime as runtime_module
from grokbuddy.infrastructure.clock import ManualClock
from grokbuddy.infrastructure.runtime import LocalRuntime
from grokbuddy.interfaces.ingress_mcp import create_ingress_mcp_server
from test_phase6_pack_b import TRIGGER_KEY, V2Flow, key


FIXTURES = Path(__file__).parent / 'fixtures' / 'review_profiles_v1_1'
LEGACY_HASHES = json.loads((FIXTURES / 'legacy_hashes.json').read_text(encoding='utf-8'))


def read_artifact(runtime, artifact_id):
    artifact = runtime.hub.get_artifact(artifact_id)
    return runtime.store.read(artifact['storage_pointer'], artifact['sha256'], artifact['size_bytes'])


def test_published_v1_0_hashes_and_profile_names_are_unchanged():
    # These hashes were captured from 1.0 before the implementation, not derived
    # from the new rules. Changing legacy order/text must fail this regression.
    assert {name: digest(rules) for name, rules in profiles.PROFILE_RULES.items()} == LEGACY_HASHES
    common = json.loads((CONTRACTS / 'common.schema.json').read_text(encoding='utf-8'))
    names = set(common['$defs']['profile']['enum'])
    for version in ('1.0', '1.1'):
        assert set(profiles.PROFILE_RULE_VERSIONS[version]) == names


def test_upgrade_adds_v1_1_without_rewriting_old_tasks_requests_or_snapshots(tmp_path, monkeypatch):
    directory = tmp_path / 'upgrade'
    clock = ManualClock()
    with monkeypatch.context() as scoped:
        scoped.setattr(runtime_module, 'PROFILE_RULE_VERSIONS', {'1.0': profiles.PROFILE_RULES})
        old = LocalRuntime(directory, CONTRACTS, clock=clock, legacy_create_test_mode=True)
        completed = Flow(old)
        completed.plan()
        history_rr = completed.request()
        completed.drive()
        assert old.hub.get_review(history_rr)['review']['reported_verdict'] == 'PASS'
        flow = Flow(old)
        flow.plan()
        rr = flow.request()
        envelope = old.hub.get_review(rr)['request']['envelope']
        snapshot = read_artifact(old, envelope['profile_artifact_id'])
        with old.db.transaction() as repo:
            before = {table: repo.find(table) for table in (
                'tasks', 'review_requests', 'review_rounds', 'reviews', 'artifacts',
                'command_receipts', 'audit_logs', 'outbox_events', 'review_profiles')}

    upgraded = LocalRuntime(directory, CONTRACTS, clock=clock, legacy_create_test_mode=True)
    with upgraded.db.transaction() as repo:
        for table, rows in before.items():
            for row in rows:
                assert repo.get(table, row['id']) == row
            if table != 'review_profiles':
                assert len(repo.find(table)) == len(rows)
        assert len(repo.find('review_profiles')) == 12
    assert read_artifact(upgraded, envelope['profile_artifact_id']) == snapshot
    assert upgraded.hub.get_review(rr)['request']['envelope'] == envelope
    # Startup is idempotent, and omission still selects 1.0 on new legacy tasks.
    upgraded._seed()
    new = upgraded.hub.create_task('builder', 'Default remains opt-in', key())
    assert (new['profile'], new['profile_version']) == ('generic', '1.0')


@pytest.mark.parametrize('version', ['1.0', '1.1'])
def test_existing_version_cannot_be_reseeded_with_changed_rules(runtime, monkeypatch, version):
    changed = deepcopy(profiles.PROFILE_RULE_VERSIONS)
    changed[version]['generic'].append('Not a new immutable version')
    with runtime.db.transaction() as repo:
        before = repo.find('review_profiles')
    monkeypatch.setattr(runtime_module, 'PROFILE_RULE_VERSIONS', changed)
    with pytest.raises(Conflict, match='without a new version'):
        runtime._seed()
    with runtime.db.transaction() as repo:
        assert repo.find('review_profiles') == before


@pytest.mark.parametrize('profile', LEGACY_HASHES)
def test_opt_in_v1_1_frozen_for_plan_and_final_with_existing_contracts(tmp_path, profile):
    # Local asynchronous mock lifecycle checks bytes and compatibility only.
    flow = V2Flow(tmp_path / profile, profile=profile, profile_version='1.1')
    plan_rr = flow.approve_plan()
    flow.begin_execution()
    flow.complete_worker()
    flow.package()
    final_rr = flow.request('FINAL_REVIEW')
    flow.drive()
    assert flow.task['state'] == 'DONE'
    for rr in (plan_rr, final_rr):
        review = flow.r.hub.get_review(rr)
        envelope = review['request']['envelope']
        assert envelope['review_profile'] == profile
        assert envelope['review_profile_version'] == '1.1'
        assert envelope['profile_sha256'] == digest(profiles.PROFILE_RULES_V1_1[profile])
        assert read_artifact(flow.r, envelope['profile_artifact_id']) == canonical(
            profiles.PROFILE_RULES_V1_1[profile])
        assert review['result']['review_profile_version'] == '1.1'
        flow.r.contracts.validate('request', envelope)
        flow.r.contracts.validate('result', review['result'])
    assert flow.task['decision_policy_version'] == 'grokbuddy-v1-dual-round'
    assert (flow.task['plan_limit'], flow.task['final_limit']) == (2, 2)


def test_new_version_registration_does_not_retarget_pending_v1_1_review(tmp_path, monkeypatch):
    flow = V2Flow(tmp_path, profile_version='1.1')
    flow.plan()
    rr = flow.request()
    before = flow.r.hub.get_review(rr)['request']
    artifact_id = before['envelope']['profile_artifact_id']
    content = read_artifact(flow.r, artifact_id)
    expanded = deepcopy(profiles.PROFILE_RULE_VERSIONS)
    expanded['1.2'] = {'generic': ['Disposable future-version fixture']}
    monkeypatch.setattr(runtime_module, 'PROFILE_RULE_VERSIONS', expanded)
    flow.r._seed()
    assert flow.r.hub.get_review(rr)['request'] == before
    assert read_artifact(flow.r, artifact_id) == content
    assert flow.task['profile_version'] == '1.1'


@pytest.mark.anyio
@pytest.mark.parametrize('version', [None, '1.1'])
async def test_ingress_default_and_explicit_opt_in_are_idempotent(tmp_path, version):
    runtime = LocalRuntime(tmp_path, CONTRACTS, clock=ManualClock(), trigger_source_key=TRIGGER_KEY)
    payload = {
        'segments': [{'source': 'user_body', 'text': PHRASE + '，本地版本兼容测试'}],
        'conversation_id': key(), 'idempotency_key': key(),
    }
    if version is not None:
        payload['profile_version'] = version
    async with Client(create_ingress_mcp_server(runtime), mode='legacy', raise_exceptions=True) as client:
        first = (await client.call_tool('create_triggered_task', payload)).structured_content
        replay = (await client.call_tool('create_triggered_task', payload)).structured_content
    assert first == replay
    assert (first['profile'], first['profile_version']) == ('generic', version or '1.0')
    with runtime.db.transaction() as repo:
        assert len(repo.find('tasks')) == 1


def test_v1_1_output_examples_use_existing_result_schema(runtime):
    sources = {'plan-pass.json': 'allslowcheck-revised.md',
               'plan-needs-changes.json': 'allslowcheck-original.md',
               'creative-final-pass.json': 'creative-pass.md'}
    for path in sorted((FIXTURES / 'results').glob('*.json')):
        result = json.loads(path.read_text(encoding='utf-8'))
        assert result['review_profile_version'] == '1.1'
        assert result['profile_sha256'] == digest(profiles.PROFILE_RULES_V1_1[result['review_profile']])
        assert result['input_sha256'] == hashlib.sha256(
            (FIXTURES / 'inputs' / sources[path.name]).read_bytes()).hexdigest()
        runtime.contracts.validate('result', result)
    assert len(list((FIXTURES / 'results').glob('*.json'))) >= 3


def test_quality_corpus_is_complete_and_keeps_oracles_separate():
    # Corpus integrity only: this test does not pretend to run an LLM evaluator.
    corpus = json.loads((FIXTURES / 'cases.json').read_text(encoding='utf-8'))
    cases = corpus['cases']
    assert corpus['execution_status'] == 'NOT_RUN'
    assert len({case['id'] for case in cases}) == len(cases)
    domains = {'software', 'data', 'document_analysis', 'web_visual', 'creative'}
    for domain in domains:
        outcomes = {case['expected_outcome'] for case in cases if case['domain'] == domain}
        assert {'PASS', 'NEEDS_CHANGES'} <= outcomes
    for case in cases:
        source = (FIXTURES / case['input_path']).resolve()
        assert source.is_relative_to((FIXTURES / 'inputs').resolve())
        assert source.is_file() and source.read_text(encoding='utf-8').strip()
        assert case['required_observations'] and case['forbidden_objections']
        assert case['review_profile'] in LEGACY_HASHES
        assert case['review_round'] in (1, 2)
        if case['review_round'] == 2:
            assert case['expected_outcome'] in ('PASS', 'BLOCK', 'TECHNICAL_FAILURE')
    assert {'minor-only', 'not-applicable', 'material-unreadable', 'hash-mismatch',
            'allslowcheck-original', 'allslowcheck-revised', 'allslowcheck-renamed',
            'r2-resolved', 'r2-substantive'} <= {case['id'] for case in cases}
