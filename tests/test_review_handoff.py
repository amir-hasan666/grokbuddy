"""Handoff safeguards in disposable local Hubs; no external or production proof."""

from copy import deepcopy
import json

import httpx2
import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from mcp import Client

from grokbuddy.adapters.sqlite import TABLES
from grokbuddy.adapters.github import FileGitHubCommentTransport
from grokbuddy.domain.model import HubError, PermissionDenied
from grokbuddy.interfaces.gateway import ClientGateway
from grokbuddy.interfaces.grok_reviewer import GrokReviewerApplication
from grokbuddy.interfaces.mcp import create_mcp_server
from test_phase6_pack_b import V2Flow, key
from test_phase4_grok_adapter import B_ACTOR, AGENT_ID, SERVER_ID, TOKEN


def snapshot(flow):
    with flow.r.db.transaction() as repo:
        return {table: repo.find(table) for table in TABLES}


def plan_review(tmp_path, *, supporting=True):
    flow = V2Flow(tmp_path / 'handoff')
    flow.r.hub.register_reviewer('system', B_ACTOR, 'Local-only Reviewer B', AGENT_ID, SERVER_ID)
    flow.plan()
    source = flow.artifact('SOURCE_FILE', 'existing source used by this Plan')
    unlisted = flow.artifact('SOURCE_FILE', 'same Task but not referenced by this Plan')
    if supporting:
        flow.r.hub.submit_plan(flow.owner, flow.task_id, flow.task['current_plan_id'],
                               flow.version, key(), approved_scope={'files': ['local.txt']},
                               supporting_artifact_ids=[source['id']])
    rr = flow.r.hub.request_review(flow.owner, flow.task_id, 'PLAN_REVIEW', B_ACTOR,
                                   flow.version, key())['review_request_id']
    intake = flow.r.grok_intake(B_ACTOR)
    dispatcher = flow.r.grok_dispatcher(FileGitHubCommentTransport(tmp_path / 'unused.json'),
                                         B_ACTOR, 'https://reviewer.example.test', intake=intake)
    assert dispatcher.dispatch_one() == 'SENT'
    adapter = dispatcher.adapter
    app = GrokReviewerApplication(flow.r, adapter, TOKEN, intake)
    return flow, rr, app, source, unlisted


def result(flow, rr):
    fields = flow.r.hub.grok_request(B_ACTOR, rr)['result_bindings']
    return dict(fields, verdict='PASS', summary='Local handoff fixture',
                reviewer={'id': B_ACTOR, 'type': 'grok_bot'},
                timestamp='2026-10-02T10:00:00Z', evidence=[], risks=[],
                recommendations=[], proposed_changes=[], findings=[], verifications=[])


def event(flow, rr, payload, event_type='ReviewCompleted'):
    envelope = flow.r.hub.get_review(rr)['request']['envelope']
    return dict(event_id='EVT-' + key(), event_type=event_type, source='grok_bot',
                task_id=flow.task_id, review_request_id=rr, review_id=envelope['review_id'],
                correlation_id=rr, deduplication_key=key(), payload=payload,
                execution={'agent_id': AGENT_ID, 'server_id': SERVER_ID,
                           'run_id': 'offline-handoff-test'})


HEADERS = {'authorization': 'Bearer ' + TOKEN}


@pytest.mark.anyio
async def test_schema_bundle_material_checks_and_result_preflight_do_not_mutate(tmp_path):
    flow, rr, app, source, unlisted = plan_review(tmp_path)
    before = snapshot(flow)
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app),
                                  base_url='https://reviewer.example.test') as client:
        assert (await client.get('/reviewer/contracts')).status_code == 401
        schemas = (await client.get('/reviewer/contracts', headers=HEADERS)).json()['schemas']
        assert len(schemas) == 4 and 'urn:collab:common:v1' in schemas
        registry = Registry().with_resources((name, Resource.from_contents(schema))
                                              for name, schema in schemas.items())
        validator = Draft202012Validator(schemas['urn:collab:result:v1'], registry=registry,
                                          format_checker=FormatChecker())
        payload = result(flow, rr)
        validator.validate(payload)
        check = (await client.get(f'/reviewer/requests/{rr}/materials/check',
                                  headers=HEADERS)).json()
        assert check['valid'] and not check['submitted']
        assert source['id'] in {item['artifact_id'] for item in check['checks']}
        assert unlisted['id'] not in {item['artifact_id'] for item in check['checks']}
        response = await client.post(f'/reviewer/requests/{rr}/validate-result',
                                      json=payload, headers=HEADERS)
        assert response.status_code == 200 and response.json()['valid']
        assert response.json()['not_checked'] == [
            'finding_transitions', 'verdict_policy', 'async_application']
    assert snapshot(flow) == before


@pytest.mark.anyio
@pytest.mark.parametrize('field,value,path,code', [
    ('protocol_version', 'unknown', '$.protocol_version', 'VALIDATION_FAILURE'),
    ('timestamp', 'invalid date', '$.timestamp', 'VALIDATION_FAILURE'),
    ('input_sha256', '0' * 64, '$.input_sha256', 'VALIDATION_FAILURE'),
    ('content_revision', 100, '$.content_revision', 'VALIDATION_FAILURE'),
    ('expected_task_version', 100, '$.expected_task_version', 'CONFLICT'),
    ('reviewer', {'id': 'other-reviewer', 'type': 'grok_bot'}, '$.reviewer.id', 'VALIDATION_FAILURE'),
])
async def test_preflight_reports_safe_schema_or_binding_location(tmp_path, field, value, path, code):
    flow, rr, app, _, _ = plan_review(tmp_path)
    payload = result(flow, rr)
    payload[field] = value
    before = snapshot(flow)
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app),
                                  base_url='https://reviewer.example.test') as client:
        response = await client.post(f'/reviewer/requests/{rr}/validate-result',
                                      json=payload, headers=HEADERS)
    assert response.status_code == 200
    assert response.json()['valid'] is False
    assert (response.json()['error_code'], response.json()['field_path']) == (code, path)
    assert response.json()['submitted'] is False
    assert snapshot(flow) == before


@pytest.mark.anyio
async def test_receipt_confirms_application_and_started_cas_refresh(tmp_path):
    flow, rr, app, _, _ = plan_review(tmp_path)
    old_version = flow.version
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app),
                                  base_url='https://reviewer.example.test') as client:
        started = event(flow, rr, {'protocol_version': 'v2'}, 'ReviewStarted')
        receipt = await client.post('/reviewer/events', json=started, headers=HEADERS)
        path = '/reviewer/ingress/' + receipt.json()['ingress_id']
        queued = (await client.get(path, headers=HEADERS)).json()
        assert queued['status'] == 'READY' and queued['accepted_review'] is None
        assert flow.r.events.handle_one() == 'APPLIED'
        assert (await client.get(path, headers=HEADERS)).json()['accepted_review'] is None
        fields = (await client.get(f'/reviewer/requests/{rr}', headers=HEADERS)).json()['result_bindings']
        assert fields['expected_task_version'] == flow.version == old_version + 1
        payload = result(flow, rr)
        payload['expected_task_version'] = old_version
        assert not flow.r.hub.grok_result_preflight(B_ACTOR, rr, payload)['valid']
        payload['expected_task_version'] = flow.version
        completed = event(flow, rr, payload)
        receipt = await client.post('/reviewer/events', json=completed, headers=HEADERS)
        path = '/reviewer/ingress/' + receipt.json()['ingress_id']
        assert (await client.get(path, headers=HEADERS)).json()['accepted_review'] is None
        assert flow.r.events.handle_one() == 'APPLIED'
        applied = (await client.get(path, headers=HEADERS)).json()
        assert applied['status'] == 'APPLIED' and applied['request_status'] == 'COMPLETED'
        assert applied['accepted_review']['effective_verdict'] == 'PASS'
        assert applied['task']['state'] == 'PLAN_APPROVED'
        replay = await client.post('/reviewer/events', json=completed, headers=HEADERS)
        assert replay.json()['ingress_id'] == receipt.json()['ingress_id']
        assert flow.r.events.handle_one() is None
        duplicate = (await client.get('/reviewer/ingress/' + replay.json()['ingress_id'],
                                       headers=HEADERS)).json()
        assert duplicate['accepted_review'] == applied['accepted_review']
        completed['event_id'] = 'EVT-' + key()
        completed['deduplication_key'] = key()
        replay = await client.post('/reviewer/events', json=completed, headers=HEADERS)
        assert flow.r.events.handle_one() == 'DUPLICATE'
        assert (await client.get('/reviewer/ingress/' + replay.json()['ingress_id'],
                                 headers=HEADERS)).json()['accepted_review'] == applied['accepted_review']
        with pytest.raises(PermissionDenied):
            flow.r.hub.grok_result_preflight(B_ACTOR, rr, payload)
        assert (await client.get(f'/reviewer/requests/{rr}/materials/check', headers=HEADERS)).json()['valid']


def test_plan_supporting_material_acl_bytes_and_history(tmp_path):
    flow, rr, _, source, unlisted = plan_review(tmp_path)
    assert flow.r.hub.grok_artifact(B_ACTOR, rr, source['id'])[1].startswith(b'existing source')
    with pytest.raises(PermissionDenied):
        flow.r.hub.grok_artifact(B_ACTOR, rr, unlisted['id'])
    envelope = flow.r.hub.get_review(rr)['request']['envelope']
    changed = flow.r.mock._result(envelope, {'scenario': 'NEEDS_CHANGES'})
    changed['reviewer']['type'] = 'grok_bot'
    normalized = flow.r.grok_dispatcher(FileGitHubCommentTransport(tmp_path / 'other.json'),
                                        B_ACTOR, 'https://reviewer.example.test').adapter.normalize_review_event(
        json.dumps(event(flow, rr, changed)).encode(), B_ACTOR)
    flow.r.events.ingest(normalized)
    assert flow.r.events.handle_one() == 'APPLIED'
    flow.plan('Revised Plan with different materials')
    flow.r.hub.submit_plan(flow.owner, flow.task_id, flow.task['current_plan_id'],
                           flow.version, key(), approved_scope={'files': ['local.txt']},
                           supporting_artifact_ids=[unlisted['id']])
    assert flow.r.hub.grok_artifact(B_ACTOR, rr, source['id'])[1].startswith(b'existing source')
    with pytest.raises(PermissionDenied):
        flow.r.hub.grok_artifact(B_ACTOR, rr, unlisted['id'])
    flow.r.store._path(source['storage_pointer']).write_bytes(b'corrupt disposable fixture')
    check = flow.r.hub.grok_materials_check(B_ACTOR, rr)
    assert check['valid'] is False
    assert any(item['artifact_id'] == source['id'] and not item['readable'] for item in check['checks'])
    assert 'storage_pointer' not in json.dumps(check)


@pytest.mark.parametrize('case', ['duplicate', 'wrong-kind', 'foreign', 'corrupt'])
def test_plan_rejects_invalid_supporting_evidence_without_partial_submit(tmp_path, case):
    flow = V2Flow(tmp_path / 'invalid-support')
    flow.plan()
    source = flow.artifact('SOURCE_FILE', 'existing source')
    ids = [source['id']]
    if case == 'duplicate':
        ids *= 2
    elif case == 'wrong-kind':
        ids = [flow.task['current_plan_id']]
    elif case == 'foreign':
        other = V2Flow(tmp_path / 'another-hub')
        ids = [other.artifact('SOURCE_FILE')['id']]
    else:
        flow.r.store._path(source['storage_pointer']).write_bytes(b'corrupted')
    before = deepcopy(flow.task)
    with pytest.raises(HubError):
        flow.r.hub.submit_plan(flow.owner, flow.task_id, flow.task['current_plan_id'],
                               flow.version, key(), approved_scope={'files': ['local.txt']},
                               supporting_artifact_ids=ids)
    assert flow.task == before


def final_inputs(flow):
    test = flow.artifact('TEST_RESULT', 'local test results')
    diff = flow.artifact('DIFF', 'local diff')
    source = flow.artifact('SOURCE_FILE', 'complete file bytes')
    return {'task_id': flow.task_id, 'test_artifact_id': test['id'], 'diff_artifact_id': diff['id'],
            'change_scope': 'bounded local change', 'changed_files': ['local.txt'],
            'self_test_summary': 'Tests passed', 'known_risks': [], 'unverified_items': [],
            'operation_method': 'Read local.txt',
            'generated_files': [{'path': 'local.txt', 'artifact_id': source['id']}]}


@pytest.mark.parametrize('case', ['method', 'files', 'wrong-kind', 'unapproved', 'bad-shape', 'corrupt'])
def test_final_preflight_and_automatic_guard_leave_business_state_unchanged(tmp_path, case):
    flow = V2Flow(tmp_path / 'final-preflight')
    flow.approve_plan()
    flow.begin_execution()
    flow.complete_worker()
    fields = final_inputs(flow)
    if case == 'method':
        fields.pop('operation_method')
    elif case == 'files':
        fields.pop('generated_files')
    elif case == 'wrong-kind':
        fields['generated_files'][0]['artifact_id'] = fields['test_artifact_id']
    elif case == 'unapproved':
        fields['changed_files'] = ['outside.txt']
        fields['generated_files'][0]['path'] = 'outside.txt'
    elif case == 'bad-shape':
        fields['generated_files'][0]['sha256'] = '0' * 64
    else:
        artifact = flow.r.hub.get_artifact(fields['generated_files'][0]['artifact_id'])
        flow.r.store._path(artifact['storage_pointer']).write_bytes(b'corrupted')
    gateway = ClientGateway(flow.r, flow.owner)
    before = snapshot(flow)
    check = gateway.invoke('preflight_final_review', fields)
    assert check['ready'] is False and check['issues'] and check['submitted'] is False
    assert snapshot(flow) == before
    with pytest.raises(HubError, match='Final material preflight'):
        gateway.invoke('request_final_review', dict(fields, expected_version=flow.version,
                                                    begin_execution=False, idempotency_key=key()))
    assert snapshot(flow) == before


@pytest.mark.anyio
async def test_mcp_preflight_readonly_annotation_and_complete_package_replay(tmp_path):
    flow = V2Flow(tmp_path / 'final-success')
    flow.approve_plan()
    flow.begin_execution()
    flow.complete_worker()
    fields = final_inputs(flow)
    before = snapshot(flow)
    async with Client(create_mcp_server(flow.r, flow.owner), mode='legacy',
                      raise_exceptions=False) as client:
        tool = next(tool for tool in (await client.list_tools()).tools
                    if tool.name == 'preflight_final_review')
        assert tool.annotations.read_only_hint is True
        response = await client.call_tool('preflight_final_review', fields)
        assert not response.is_error
    assert snapshot(flow) == before
    gateway = ClientGateway(flow.r, flow.owner)
    payload = dict(fields, expected_version=flow.version, begin_execution=False, idempotency_key=key())
    receipt = gateway.invoke('request_final_review', payload)
    assert receipt['status'] == 'PENDING'
    assert gateway.invoke('request_final_review', payload) == receipt
    assert len(flow.rows('review_requests', task_id=flow.task_id, review_type='FINAL_REVIEW')) == 1
