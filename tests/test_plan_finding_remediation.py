"""Plan remediation and receipt diagnostics in disposable local storage only."""

from copy import copy, deepcopy
import json

import httpx2
import pytest
from mcp import Client

from grokbuddy.adapters.sqlite import TABLES
from grokbuddy.application.common import uid
from grokbuddy.application.trigger import PHRASE, issue_trigger_evidence
from grokbuddy.domain.model import HubError, NormalizedEvent, PermissionDenied
from grokbuddy.interfaces.gateway import ClientGateway
from grokbuddy.interfaces.grok_reviewer import GrokReviewerApplication
from grokbuddy.interfaces.mcp import create_mcp_server
from test_phase6_pack_b import TRIGGER_KEY, V2Flow, key


B_ACTOR = 'grok-reviewer-b'
AGENT_ID = '4335c388-584c-434e-b14e-13964b176b6e'
SERVER_ID = '3504754'
TOKEN = 'local-only-remediation-reviewer-token'
EXECUTION = {'agent_id': AGENT_ID, 'server_id': SERVER_ID, 'run_id': 'local-remediation-test'}
PRIVATE_TEXT = 'private-payload-text-must-not-be-a-diagnostic'


def result_for(flow, rr, verdict):
    request = flow.r.hub.get_review(rr)['request']['envelope']
    payload = flow.r.mock._result(request, {'scenario': verdict})
    if request['expected_reviewer_actor_id'] == B_ACTOR:
        payload['reviewer']['type'] = 'grok_bot'
    return payload


def ingest(flow, rr, payload):
    envelope = flow.r.hub.get_review(rr)['request']['envelope']
    actor = envelope['expected_reviewer_actor_id']
    return flow.r.events.ingest(NormalizedEvent(
        uid('EVT'), 'ReviewCompleted', 'grok_bot' if actor == B_ACTOR else 'local-test',
        actor, flow.task_id, rr, envelope['review_id'], rr, key(), payload,
        EXECUTION if actor == B_ACTOR else None))


def changed_plan(flow, *, reviewer='mock-reviewer', count=1):
    flow.plan('Initial local Plan')
    if reviewer == B_ACTOR:
        flow.r.hub.register_reviewer('system', B_ACTOR, 'Local Reviewer B', AGENT_ID, SERVER_ID)
    rr = flow.r.hub.request_review(flow.owner, flow.task_id, 'PLAN_REVIEW', reviewer,
                                  flow.version, key())['review_request_id']
    payload = result_for(flow, rr, 'NEEDS_CHANGES')
    payload['summary'] = PRIVATE_TEXT
    if count == 2:
        second = deepcopy(payload['findings'][0])
        second.update(external_finding_key='second-risk', severity='MEDIUM')
        payload['findings'].append(second)
    ingest(flow, rr, payload)
    assert flow.r.events.handle_one() == 'APPLIED'
    return rr, flow.r.hub.list_findings(flow.task_id)


def other_task_in_same_hub(flow):
    message = dict(principal_id=flow.owner, conversation_id=key(), message_id=key(),
                   turn_id=key(), message_role='user', issued_at=flow.r.clock.now(),
                   segments=[{'source': 'user_body', 'text': PHRASE + '，隔离的其他任务'}])
    body, evidence = issue_trigger_evidence(message, TRIGGER_KEY, flow.r.clock.now())
    other = copy(flow)
    other.task_id = flow.r.hub.create_task(flow.owner, body, key(), trigger_evidence=evidence)['id']
    return other


def respond(gateway, flow, finding, action, evidence=None, **changes):
    payload = dict(task_id=flow.task_id, review_id=finding['review_id'], finding_id=finding['id'],
                   action=action, expected_version=flow.version, idempotency_key=key())
    if evidence is not None:
        payload['evidence_artifact_id'] = evidence['id']
    payload.update(changes)
    return gateway.invoke('respond_to_review', payload)


def snapshot(flow, tables=TABLES):
    return {table: flow.rows(table) for table in sorted(tables)}


BUSINESS_TABLES = TABLES - {'inbox_events', 'audit_logs'}


def verifications(findings, evidence):
    return [{'finding_id': finding['id'], 'outcome': 'VERIFIED',
             'evidence': {'artifact_id': evidence, 'locator': 'local-plan-correction',
                          'description': PRIVATE_TEXT}, 'reason': PRIVATE_TEXT}
            for finding in findings]


def test_gateway_plan_accept_fix_replay_and_r2_verification_approve_without_execution(tmp_path):
    flow = V2Flow(tmp_path)
    first, findings = changed_plan(flow, reviewer=B_ACTOR, count=2)
    gateway = ClientGateway(flow.r, 'builder')
    for finding in findings:
        assert respond(gateway, flow, finding, 'accept')['finding']['status'] == 'ACCEPTED'
    artifact = flow.artifact('PLAN', 'Revised local Plan')
    evidence = flow.artifact('EVIDENCE', 'Each R1 Finding mapped to revised Plan ' + artifact['id'])
    gateway.invoke('submit_plan', {
        'task_id': flow.task_id, 'plan_artifact_id': artifact['id'],
        'approved_scope': {'files': ['local.txt']},
        'supporting_artifact_ids': [evidence['id']],
        'expected_version': flow.version, 'idempotency_key': key(),
    })
    for finding in findings:
        version, command_key = flow.version, key()
        fixed = respond(gateway, flow, finding, 'fix', evidence,
                        expected_version=version, idempotency_key=command_key)
        assert fixed['finding']['status'] == 'FIXED'
        assert flow.task['state'] == 'PLANNING'
        assert flow.version == version + 1
        assert respond(gateway, flow, finding, 'fix', evidence,
                       expected_version=version, idempotency_key=command_key) == fixed
    assert not flow.rows('worker_assignments', task_id=flow.task_id)
    assert len(flow.rows('review_requests', task_id=flow.task_id)) == 1
    readiness = gateway.invoke('get_plan_review_readiness', {'task_id': flow.task_id})
    assert readiness['ready_for_review'] and readiness['unready_findings'] == []
    assert readiness['unbound_fix_evidence'] == []
    assert all(finding['fix_evidence_bound'] for finding in readiness['findings'])
    assert readiness['next_review_round'] == 2 and readiness['rounds_remaining'] == 1
    second = gateway.invoke('request_plan_review', {
        'task_id': flow.task_id, 'expected_version': readiness['expected_task_version'],
        'reviewer_id': B_ACTOR, 'idempotency_key': key(),
    })['review_request_id']
    assert flow.r.hub.get_review(second)['request']['status'] == 'PENDING'
    materials = flow.r.hub.grok_materials(B_ACTOR, second)['artifacts']
    assert materials['supporting_artifacts'] == [
        {'artifact_id': evidence['id'], 'sha256': evidence['sha256']}]
    assert flow.r.hub.grok_artifact(B_ACTOR, second, evidence['id'])[0]['sha256'] == evidence['sha256']
    payload = result_for(flow, second, 'PASS')
    payload['verifications'] = verifications(findings, evidence['id'])
    ingest(flow, second, payload)
    assert flow.task['state'] == 'PLAN_REVIEW_PENDING'
    assert flow.r.events.handle_one() == 'APPLIED'
    assert flow.task['state'] == 'PLAN_APPROVED'
    assert all(f['status'] == 'VERIFIED' for f in flow.r.hub.list_findings(flow.task_id))
    assert len(flow.rows('finding_events', task_id=flow.task_id)) == 8
    assert flow.r.hub.get_review(first)['review']['reported_verdict'] == 'NEEDS_CHANGES'
    assert not flow.rows('worker_assignments', task_id=flow.task_id)


@pytest.mark.parametrize('case', ['active', 'stale', 'plan-evidence', 'foreign-evidence',
                                  'open', 'wrong-state', 'reviewer-role'])
def test_plan_fix_keeps_existing_guards_and_never_starts_execution(tmp_path, case):
    flow = V2Flow(tmp_path / case)
    _, findings = changed_plan(flow)
    finding = findings[0]
    gateway = ClientGateway(flow.r, 'builder')
    if case != 'open':
        respond(gateway, flow, finding, 'accept')
    if case != 'wrong-state':
        flow.plan('Revised local Plan')
    evidence = flow.artifact('DIFF', 'Local correction evidence')
    if case == 'plan-evidence':
        evidence = {'id': flow.task['current_plan_id']}
    if case == 'foreign-evidence':
        evidence = other_task_in_same_hub(flow).artifact('DIFF', 'Other Task evidence')
    if case == 'active':
        flow.request()
    if case == 'reviewer-role':
        gateway = ClientGateway(flow.r, 'mock-reviewer')
    before = snapshot(flow, BUSINESS_TABLES)
    changes = {'expected_version': flow.version - 1} if case == 'stale' else {}
    with pytest.raises(HubError):
        respond(gateway, flow, finding, 'fix', evidence, **changes)
    assert snapshot(flow, BUSINESS_TABLES) == before
    assert not flow.rows('worker_assignments', task_id=flow.task_id)


def test_readiness_is_read_only_scoped_and_does_not_ban_unready_r2_requests(tmp_path):
    flow = V2Flow(tmp_path)
    _, findings = changed_plan(flow)
    flow.plan('Revised Plan with response still missing')
    gateway = ClientGateway(flow.r, 'builder')
    before = snapshot(flow)
    readiness = gateway.invoke('get_plan_review_readiness', {'task_id': flow.task_id})
    assert readiness['can_request_review'] and not readiness['ready_for_review']
    assert readiness['unready_findings'] == [findings[0]['id']]
    assert readiness['findings'][0]['review_id'] == findings[0]['review_id']
    assert snapshot(flow) == before
    with pytest.raises(PermissionDenied):
        ClientGateway(flow.r, 'workbuddy-worker').invoke(
            'get_plan_review_readiness', {'task_id': flow.task_id})
    with pytest.raises(PermissionDenied):
        ClientGateway(flow.r, 'mock-reviewer').invoke(
            'get_plan_review_readiness', {'task_id': flow.task_id})
    with pytest.raises(HubError):
        gateway.invoke_query('get_plan_review_readiness', {'task_id': flow.task_id})
    # It is a workflow hint, not a new blanket guard against a legitimate R2 BLOCK.
    second = flow.request(scenario='BLOCK')
    payload = result_for(flow, second, 'BLOCK')
    assert ingest(flow, second, payload)
    assert flow.r.events.handle_one() == 'APPLIED'
    assert flow.task['state'] == 'PLAN_HUMAN_REVIEW'


def test_readiness_reports_r2_timeout_without_mutation_or_third_round(tmp_path):
    flow = V2Flow(tmp_path)
    changed_plan(flow)
    flow.plan('Revised Plan')
    second = flow.request()
    flow.r.clock.advance(flow.r.settings.plan_review_timeout + 1)
    flow.r.timeouts.sweep()
    before = snapshot(flow)
    readiness = ClientGateway(flow.r, 'builder').invoke(
        'get_plan_review_readiness', {'task_id': flow.task_id})
    assert readiness['task_state'] == 'PLAN_HUMAN_REVIEW'
    assert readiness['gate_reason'] == 'REVIEW_TIMEOUT'
    assert readiness['rounds_remaining'] == 0 and readiness['next_review_round'] == 3
    assert not readiness['can_request_review'] and not readiness['ready_for_review']
    assert snapshot(flow) == before
    assert flow.r.hub.get_review(second)['request']['status'] == 'TIMED_OUT'
    with pytest.raises(HubError, match='two-round'):
        flow.r.hub.human_gate_decide('human', flow.task_id, 'CONTINUE', 'Local attempt',
                                   flow.version, key(), new_deadline_at=flow.r.clock.now() + 60_000_000)


@pytest.mark.anyio
async def test_mcp_readiness_annotation_and_plan_fix_use_same_application_guards(tmp_path):
    flow = V2Flow(tmp_path)
    _, findings = changed_plan(flow)
    finding = findings[0]
    server = create_mcp_server(flow.r)
    async with Client(server, mode='legacy', raise_exceptions=True) as client:
        tools = (await client.list_tools()).tools
        tool = next(t for t in tools if t.name == 'get_plan_review_readiness')
        assert tool.annotations.model_dump(by_alias=True)['readOnlyHint'] is True
        before = snapshot(flow)
        call = await client.call_tool('get_plan_review_readiness', {'task_id': flow.task_id})
        assert call.structured_content['findings'][0]['current_status'] == 'OPEN'
        assert snapshot(flow) == before
        await client.call_tool('respond_to_review', dict(
            task_id=flow.task_id, review_id=finding['review_id'], finding_id=finding['id'],
            action='accept', expected_version=flow.version, idempotency_key=key()))
        flow.plan('Revised Plan')
        evidence = flow.artifact('DIFF')
        fixed = await client.call_tool('respond_to_review', dict(
            task_id=flow.task_id, review_id=finding['review_id'], finding_id=finding['id'],
            action='fix', expected_version=flow.version, idempotency_key=key(),
            evidence_artifact_id=evidence['id']))
        assert fixed.structured_content['finding']['status'] == 'FIXED'
        assert flow.task['state'] == 'PLANNING'


@pytest.mark.anyio
async def test_async_rejection_stores_complete_safe_transition_details_and_keeps_history(tmp_path):
    flow = V2Flow(tmp_path)
    changed_plan(flow, reviewer=B_ACTOR, count=2)
    findings = flow.r.hub.list_findings(flow.task_id)
    flow.plan('Revised Plan whose Finding responses were omitted')
    second = flow.r.hub.request_review(flow.owner, flow.task_id, 'PLAN_REVIEW', B_ACTOR,
                                      flow.version, key())['review_request_id']
    payload = result_for(flow, second, 'PASS')
    payload['summary'] = PRIVATE_TEXT
    payload['verifications'] = verifications(findings, flow.task['current_plan_id'])
    intake = flow.r.grok_intake(B_ACTOR)
    dispatcher = flow.r.grok_dispatcher(None, B_ACTOR, 'https://local.test', intake=intake)
    app = GrokReviewerApplication(flow.r, dispatcher.adapter, TOKEN, intake=intake)
    envelope = flow.r.hub.get_review(second)['request']['envelope']
    event = dict(event_id=uid('EVT'), event_type='ReviewCompleted', source='grok_bot',
                 task_id=flow.task_id, review_request_id=second, review_id=envelope['review_id'],
                 correlation_id=second, deduplication_key=key(), payload=payload, execution=EXECUTION)
    headers = {'authorization': 'Bearer ' + TOKEN}
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url='https://local.test') as client:
        receipt = await client.post('/reviewer/events', json=event, headers=headers)
        assert receipt.status_code == 202 and receipt.json()['status'] == 'READY'
        ingress_id = receipt.json()['ingress_id']
        before = snapshot(flow, BUSINESS_TABLES)
        assert flow.r.events.handle_one() == 'REJECTED'
        assert snapshot(flow, BUSINESS_TABLES) == before
        query_before = snapshot(flow)
        response = await client.get('/reviewer/ingress/' + ingress_id, headers=headers)
        assert response.status_code == 200
        assert snapshot(flow) == query_before
        status = response.json()
        assert status['error_code'] == 'ILLEGAL_TRANSITION'
        assert status['reason_code'] == 'FINDING_NOT_READY_FOR_VERIFICATION'
        assert status['field_path'] == '$.verifications[0].finding_id'
        assert status['field_path_source'] == status['rejection_details_source'] == 'STORED'
        details = status['rejection_details']
        assert details['blocking_open_findings'] == [f['id'] for f in findings]
        assert len(details['invalid_finding_transitions']) == 2
        for index, item in enumerate(details['invalid_finding_transitions']):
            assert item['current_status'] == 'OPEN'
            assert item['allowed_statuses'] == ['FIXED', 'REJECTED_WITH_EVIDENCE']
            assert item['field_path'] == f'$.verifications[{index}].finding_id'
        assert PRIVATE_TEXT not in response.text and TOKEN not in response.text
        rejection_audit = flow.rows('audit_logs')[-1]['payload_summary']
        assert rejection_audit['reason_code'] == status['reason_code']
        assert PRIVATE_TEXT not in json.dumps(rejection_audit)
        assert (await client.get('/reviewer/ingress/' + ingress_id)).status_code == 401
        flow.r.hub.register_reviewer('system', 'grok-reviewer-other', 'Other local reviewer',
                                     '33333333-3333-3333-3333-333333333333', '3504755')
        with pytest.raises(PermissionDenied):
            flow.r.hub.grok_ingress_status('grok-reviewer-other', ingress_id)
        flow.r.clock.advance(flow.r.settings.plan_review_timeout + 1)
        flow.r.timeouts.sweep()
        flow.r.hub.waive_finding('human', findings[0]['id'], 'Local snapshot stability test',
                                flow.version, key())
        history_before = snapshot(flow)
        after_timeout = (await client.get('/reviewer/ingress/' + ingress_id, headers=headers)).json()
        for field in ('status', 'error_code', 'field_path', 'field_path_source', 'reason_code',
                      'rejection_details', 'rejection_details_source'):
            assert after_timeout[field] == status[field]
        assert snapshot(flow) == history_before
        # Legacy receipt metadata is not invented by querying today's Finding states.
        with flow.r.db.transaction() as repo:
            legacy = repo.get('inbox_events', ingress_id)
            legacy.pop('rejection_details')
            legacy.pop('field_path')
            repo.save('inbox_events', legacy)
        legacy_before = snapshot(flow)
        legacy_status = (await client.get('/reviewer/ingress/' + ingress_id, headers=headers)).json()
        assert legacy_status['reason_code'] is None and legacy_status['rejection_details'] is None
        assert legacy_status['rejection_details_source'] is None
        assert snapshot(flow) == legacy_before


def test_pass_without_verification_explains_fixed_but_unclosed_findings(tmp_path):
    flow = V2Flow(tmp_path)
    _, findings = changed_plan(flow)
    gateway = ClientGateway(flow.r, 'builder')
    respond(gateway, flow, findings[0], 'accept')
    flow.plan('Revised Plan')
    respond(gateway, flow, findings[0], 'fix', flow.artifact('DIFF'))
    readiness = gateway.invoke('get_plan_review_readiness', {'task_id': flow.task_id})
    assert readiness['can_request_review'] and not readiness['ready_for_review']
    assert readiness['unready_findings'] == []
    assert readiness['unbound_fix_evidence'] == [findings[0]['id']]
    second = flow.request()
    ingress_id = ingest(flow, second, result_for(flow, second, 'PASS'))
    before = snapshot(flow, BUSINESS_TABLES)
    assert flow.r.events.handle_one() == 'REJECTED'
    assert snapshot(flow, BUSINESS_TABLES) == before
    details = flow.rows('inbox_events', id=ingress_id)[0]['rejection_details']
    assert details['reason_code'] == 'PASS_HAS_UNRESOLVED_FINDINGS'
    assert details['field_path'] == '$.verdict'
    assert details['unresolved_findings'][0]['current_status'] == 'FIXED'
    assert details['blocking_open_findings'] == []


def test_foreign_verification_never_exposes_other_task_diagnostics(tmp_path):
    flow = V2Flow(tmp_path)
    _, findings = changed_plan(flow)
    flow.plan('Revised Plan')
    other = other_task_in_same_hub(flow)
    _, other_findings = changed_plan(other)
    second = flow.request()
    payload = result_for(flow, second, 'PASS')
    payload['verifications'] = verifications(findings + other_findings, flow.task['current_plan_id'])
    ingress_id = ingest(flow, second, payload)
    before = snapshot(flow, BUSINESS_TABLES)
    assert flow.r.events.handle_one() == 'REJECTED'
    assert snapshot(flow, BUSINESS_TABLES) == before
    receipt = flow.rows('inbox_events', id=ingress_id)[0]
    assert receipt['error_code'] == 'CONFLICT'
    assert 'rejection_details' not in receipt
