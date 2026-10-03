"""Scope/material separation in disposable local Hubs; no production acceptance."""

from copy import deepcopy
import json

import pytest
from mcp import Client

from grokbuddy.application.common import canonical, digest
from grokbuddy.domain.model import HubError, PermissionDenied
from grokbuddy.interfaces.gateway import ClientGateway
from grokbuddy.interfaces.mcp import create_mcp_server
from test_phase6_pack_b import V2Flow, key
from test_plan_finding_remediation import ingest, result_for, snapshot
from test_phase4_grok_adapter import B_ACTOR, AGENT_ID, SERVER_ID


FUTURE_FILES = ['WCAUTOASK/app/main.py', 'WCAUTOASK/scripts/phase0_probe.py']


def reviewer_flow(tmp_path):
    flow = V2Flow(tmp_path, profile_version='1.1')
    flow.r.hub.register_reviewer('system', B_ACTOR, 'Local scope Reviewer', AGENT_ID, SERVER_ID)
    return flow


def request(flow):
    return flow.r.hub.request_review(flow.owner, flow.task_id, 'PLAN_REVIEW', B_ACTOR,
                                     flow.version, key())['review_request_id']


def frozen_context(flow, rr):
    context_id = flow.r.hub.get_review(rr)['request']['context_artifact_id']
    artifact, content = flow.r.hub.grok_artifact(B_ACTOR, rr, context_id)
    assert digest(json.loads(content)) == artifact['sha256']
    return artifact, content, json.loads(content)


def test_future_files_and_supporting_materials_are_independent_and_pass_is_async(tmp_path):
    flow = reviewer_flow(tmp_path)
    scope = {'summary': 'Implement app after Plan PASS', 'files': FUTURE_FILES,
             'components': ['app', 'phase0']}
    flow.plan('Only the Plan exists; app implementation follows review', scope)
    source = flow.artifact('SOURCE_FILE', 'Existing engine source needed for review')
    evidence = flow.artifact('EVIDENCE', 'Repository selection evidence needed now')
    unlisted = flow.artifact('EVIDENCE', 'Not needed for this review')
    flow.r.hub.submit_plan(flow.owner, flow.task_id, flow.task['current_plan_id'],
                           flow.version, key(), approved_scope=scope,
                           supporting_artifact_ids=[source['id'], evidence['id']])
    before = snapshot(flow)
    readiness = ClientGateway(flow.r, 'builder').invoke('get_plan_review_readiness', {
        'task_id': flow.task_id, 'planned_changed_files': FUTURE_FILES})
    assert readiness['ready_for_review']
    assert readiness['scope_readiness']['file_coverage'] == 'COMPLETE'
    assert snapshot(flow) == before
    assert all(not (tmp_path / path).exists() for path in FUTURE_FILES)
    rr = request(flow)
    _, _, context = frozen_context(flow, rr)
    assert context['plan_scope'] == {'schema_version': 1, 'scope': scope, 'sha256': digest(scope)}
    flow.r.contracts.validate('plan-scope-snapshot', context['plan_scope'])
    assert context['supporting_artifacts'] == [
        {'artifact_id': item['id'], 'sha256': item['sha256']} for item in (source, evidence)]
    assert 'EVIDENCE' not in json.dumps(context['plan_scope']['scope']['files'])
    assert flow.r.hub.grok_artifact(B_ACTOR, rr, evidence['id'])[1].startswith(b'Repository')
    with pytest.raises(PermissionDenied):
        flow.r.hub.grok_artifact(B_ACTOR, rr, unlisted['id'])
    payload = result_for(flow, rr, 'PASS')
    ingest(flow, rr, payload)
    assert flow.task['state'] == 'PLAN_REVIEW_PENDING'
    assert flow.r.events.handle_one() == 'APPLIED'
    assert flow.task['approved_scope'] == scope
    assert flow.task['approved_scope_hash'] == digest(scope)
    assert not flow.rows('worker_assignments', task_id=flow.task_id)


def test_each_rr_keeps_its_original_scope_bytes_after_plan_revision(tmp_path):
    flow = reviewer_flow(tmp_path)
    first_scope = {'files': ['WCAUTOASK/PLAN.md']}
    flow.plan('Original document-only declaration', first_scope)
    first = request(flow)
    original = frozen_context(flow, first)
    ingest(flow, first, result_for(flow, first, 'NEEDS_CHANGES'))
    assert flow.r.events.handle_one() == 'APPLIED'
    revised_scope = {'files': ['WCAUTOASK/PLAN.md', *FUTURE_FILES],
                     'components': ['plan', 'app', 'phase0']}
    flow.plan('Revised declaration of the Task deliverables', revised_scope)
    assert frozen_context(flow, first) == original
    second = request(flow)
    second_context = frozen_context(flow, second)[2]
    assert second_context['plan_scope']['scope'] == revised_scope
    assert second_context['plan_scope']['sha256'] == digest(revised_scope)
    assert frozen_context(flow, first)[2]['plan_scope']['scope'] == first_scope
    assert len(flow.rows('review_requests', task_id=flow.task_id)) == 2
    before = snapshot(flow)
    readiness = flow.r.hub.get_plan_review_readiness(flow.owner, flow.task_id, FUTURE_FILES)
    assert readiness['rounds_remaining'] == 0 and not readiness['can_request_review']
    assert snapshot(flow) == before


def test_incomplete_scope_is_diagnosed_without_writing_or_expanding_it(tmp_path):
    flow = V2Flow(tmp_path)
    scope = {'files': ['WCAUTOASK/PLAN.md'], 'components': ['plan-document']}
    flow.plan('This Plan also promises an app, not just a document', scope)
    before = snapshot(flow)
    readiness = ClientGateway(flow.r, 'builder').invoke('get_plan_review_readiness', {
        'task_id': flow.task_id, 'planned_changed_files': ['WCAUTOASK/PLAN.md', *FUTURE_FILES]})
    check = readiness['scope_readiness']
    assert check['missing_planned_files'] == sorted(FUTURE_FILES)
    assert check['file_coverage'] == 'INCOMPLETE'
    assert check['issues'][0]['error_code'] == 'PLAN_SCOPE_FILES_INCOMPLETE'
    assert readiness['can_request_review'] and not readiness['ready_for_review']
    assert flow.task['current_plan_scope'] == scope
    assert snapshot(flow) == before


@pytest.mark.parametrize('profile', ['generic', 'document'])
def test_document_only_task_is_valid_when_its_declared_outputs_are_documents(tmp_path, profile):
    flow = V2Flow(tmp_path, profile=profile)
    flow.plan('Deliver the requested design document only', {'files': ['docs/design.md']})
    check = flow.r.hub.get_plan_review_readiness(flow.owner, flow.task_id, ['docs/design.md'])
    assert check['ready_for_review']
    assert check['scope_readiness']['file_coverage'] == 'COMPLETE'
    assert check['scope_readiness']['issues'] == []


def test_omitted_manifest_preserves_old_call_but_never_claims_coverage(tmp_path):
    flow = V2Flow(tmp_path)
    flow.plan()
    before = snapshot(flow)
    check = ClientGateway(flow.r, flow.owner).invoke('get_plan_review_readiness', {'task_id': flow.task_id})
    assert check['ready_for_review']
    assert check['scope_readiness']['file_coverage'] == 'NOT_CHECKED'
    assert check['scope_readiness']['planned_files_checked'] is False
    assert 'planned_file_coverage' in check['scope_readiness']['not_checked']
    assert snapshot(flow) == before


@pytest.mark.parametrize('scope,code', [
    ({'summary': 'Task with files not yet enumerated'}, 'PLAN_SCOPE_FILES_MISSING'),
    ({'files': ['WCAUTOASK/app/*.py']}, 'PLAN_SCOPE_FILES_NOT_EXACT'),
    ({'files': ['WCAUTOASK/app/']}, 'PLAN_SCOPE_FILES_NOT_EXACT'),
])
def test_missing_or_nonexact_file_scope_is_reported_early(tmp_path, scope, code):
    flow = V2Flow(tmp_path)
    flow.plan(scope=scope)
    before = snapshot(flow)
    check = flow.r.hub.get_plan_review_readiness(flow.owner, flow.task_id)
    assert not check['ready_for_review']
    assert code in {issue['error_code'] for issue in check['scope_readiness']['issues']}
    assert snapshot(flow) == before


@pytest.mark.parametrize('paths', [[], 'app/main.py', ['a.py', 'a.py'], ['../a.py'],
                                  ['app/*.py'], ['D:/private.py'], [42], [{'path': 'a.py'}]])
def test_invalid_planned_paths_are_rejected_without_mutation(tmp_path, paths):
    flow = V2Flow(tmp_path)
    flow.plan()
    before = snapshot(flow)
    with pytest.raises(HubError, match='planned_changed_files'):
        ClientGateway(flow.r, flow.owner).invoke('get_plan_review_readiness', {
            'task_id': flow.task_id, 'planned_changed_files': paths})
    assert snapshot(flow) == before


def test_scope_hash_mismatch_fails_before_creating_a_review_request(tmp_path):
    flow = reviewer_flow(tmp_path)
    flow.plan()
    # Deliberately corrupt disposable local state; never operate on the formal Hub.
    with flow.r.db.transaction() as repo:
        task = repo.get('tasks', flow.task_id)
        task['current_plan_scope_hash'] = '0' * 64
        repo.save('tasks', task)
    check = flow.r.hub.get_plan_review_readiness(flow.owner, flow.task_id)
    assert check['scope_readiness']['issues'][0]['error_code'] == 'PLAN_SCOPE_HASH_MISMATCH'
    before = deepcopy(flow.task)
    with pytest.raises(HubError, match='Plan scope hash mismatch'):
        request(flow)
    assert flow.task == before
    assert not flow.rows('review_requests', task_id=flow.task_id)
    assert not flow.rows('review_rounds', task_id=flow.task_id)


def test_historical_context_without_scope_is_not_rebuilt_or_migrated(tmp_path, monkeypatch):
    flow = reviewer_flow(tmp_path)
    flow.plan()
    original_add = flow.r.hub.add_artifact

    def old_context(repo, task_id, actor, kind, content, mime='application/json'):
        if kind == 'SOURCE_FILE':
            value = json.loads(content)
            if 'plan_scope' in value:
                value.pop('plan_scope')
                content = canonical(value)
        return original_add(repo, task_id, actor, kind, content, mime)

    with monkeypatch.context() as patch:
        patch.setattr(flow.r.hub, 'add_artifact', old_context)
        rr = request(flow)
    before = snapshot(flow)
    _, _, context = frozen_context(flow, rr)
    assert 'plan_scope' not in context
    assert context == {'findings': []}
    assert snapshot(flow) == before


@pytest.mark.anyio
async def test_mcp_describes_scope_and_exposes_optional_read_only_coverage_input(tmp_path):
    flow = V2Flow(tmp_path)
    flow.plan(scope={'files': ['docs/design.md']})
    async with Client(create_mcp_server(flow.r), mode='legacy', raise_exceptions=True) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        schema = tools['submit_plan'].input_schema['$defs']['ApprovedPlanScope']
        assert 'future files' in schema['properties']['files']['description']
        readiness_tool = tools['get_plan_review_readiness']
        assert readiness_tool.input_schema['required'] == ['task_id']
        assert 'planned_changed_files' in readiness_tool.input_schema['properties']
        assert readiness_tool.annotations.model_dump(by_alias=True)['readOnlyHint'] is True
        before = snapshot(flow)
        call = await client.call_tool('get_plan_review_readiness', {
            'task_id': flow.task_id, 'planned_changed_files': ['docs/design.md', 'app/main.py']})
        assert call.structured_content['scope_readiness']['missing_planned_files'] == ['app/main.py']
        assert snapshot(flow) == before
