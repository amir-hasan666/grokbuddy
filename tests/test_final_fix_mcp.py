"""Final remediation through the client surface, in disposable local Hubs only."""

from copy import deepcopy

import pytest
from mcp import Client

from grokbuddy.domain.model import HubError
from grokbuddy.interfaces.gateway import ClientGateway
from grokbuddy.interfaces.mcp import create_mcp_server
from grokbuddy.interfaces.worker_mcp import WORKER_TOOL_NAMES
from test_phase6_pack_b import V2Flow, key
from test_review_handoff import final_inputs, snapshot


def review_counts(flow):
    return tuple(len(flow.rows('review_requests', review_type=kind))
                 for kind in ('PLAN_REVIEW', 'FINAL_REVIEW'))


def begin_fields(flow, findings):
    return dict(task_id=flow.task_id, finding_ids=[item['id'] for item in findings],
                proposed_scope={'files': ['local.txt']}, expected_version=flow.version,
                idempotency_key=key())


def respond_fields(flow, finding, action, evidence=None):
    fields = dict(task_id=flow.task_id, review_id=finding['review_id'],
                  finding_id=finding['id'], action=action, expected_version=flow.version,
                  idempotency_key=key())
    if evidence:
        fields['evidence_artifact_id'] = evidence
    return fields


def three_final_findings(flow):
    flow.approve_plan()
    flow.begin_execution()
    flow.complete_worker()
    flow.package()
    rr = flow.request('FINAL_REVIEW', 'NEEDS_CHANGES')
    envelope = flow.r.hub.get_review(rr)['request']['envelope']
    template = flow.r.mock._result(envelope, {'scenario': 'NEEDS_CHANGES'})['findings'][0]
    findings = [dict(deepcopy(template), external_finding_key=f'final-fix-{index}')
                for index in range(3)]
    flow.r.mock.configure(rr, 'NEEDS_CHANGES', findings=findings)
    flow.drive()
    assert flow.task['state'] == 'FINAL_CHANGES_REQUIRED'
    return flow.r.hub.list_actionable_findings(flow.task_id)


@pytest.mark.anyio
@pytest.mark.parametrize('verdict', ['PASS', 'BLOCK'])
async def test_mcp_three_final_fixes_worker_and_r2_keep_independent_review(tmp_path, verdict):
    flow = V2Flow(tmp_path)
    findings = three_final_findings(flow)
    async with Client(create_mcp_server(flow.r), mode='legacy', raise_exceptions=True) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        tool = tools['begin_final_fix']
        assert tool.annotations.read_only_hint is False
        assert tool.annotations.idempotent_hint is True
        assert tool.input_schema['additionalProperties'] is False
        assert set(tool.input_schema['required']) == {
            'task_id', 'finding_ids', 'proposed_scope', 'expected_version', 'idempotency_key'}
        assert tool.input_schema['properties']['finding_ids']['minItems'] == 1
        assert tool.input_schema['$defs']['ApprovedPlanScope']['additionalProperties'] is False
        assert 'begin_final_fix' not in WORKER_TOOL_NAMES

        for finding in findings:
            await client.call_tool('respond_to_review', respond_fields(flow, finding, 'accept'))
        fields = begin_fields(flow, findings)
        rounds = review_counts(flow)
        begun = (await client.call_tool('begin_final_fix', fields)).structured_content
        assert begun['status'] == 'EXECUTING'
        assert begun['assignment']['finding_ids'] == fields['finding_ids']
        assert begun['assignment']['generation'] == 2
        before = snapshot(flow)
        replay = (await client.call_tool('begin_final_fix', fields)).structured_content
        assert replay == begun and snapshot(flow) == before
        assert review_counts(flow) == rounds
        assert flow.task['plan_limit'] == flow.task['final_limit'] == 2

        with pytest.raises(HubError, match='Idempotency key reused'):
            ClientGateway(flow.r).invoke('begin_final_fix', dict(fields,
                proposed_scope={'summary': 'Changed retry input', 'files': ['local.txt']}))
        assert len(flow.rows('worker_assignments')) == 2

        materials = final_inputs(flow)
        gateway = ClientGateway(flow.r)
        with pytest.raises(HubError, match='Latest Worker assignment must complete'):
            gateway.invoke('request_final_review', dict(materials, begin_execution=False,
                expected_version=flow.version, idempotency_key=key()))
        assert flow.task['state'] == 'EXECUTING' and review_counts(flow)[1] == 1
        completed = flow.complete_worker()
        for finding in findings:
            fields = respond_fields(flow, finding, 'fix', completed['completion_artifact_id'])
            fixed = (await client.call_tool('respond_to_review', fields)).structured_content
            assert fixed['finding']['status'] == 'FIXED' and not fixed['review_requested']
            before = snapshot(flow)
            assert (await client.call_tool('respond_to_review', fields)).structured_content == fixed
            assert snapshot(flow) == before
        assert flow.task['state'] == 'EXECUTING'
        receipt = (await client.call_tool('request_final_review', dict(materials,
            begin_execution=False, reviewer_id='mock-reviewer', expected_version=flow.version,
            idempotency_key=key()))).structured_content
        assert receipt['status'] == 'PENDING'
        rr = receipt['review_request_id']
        assert flow.r.hub.get_review(rr)['review'] is None
        assert flow.task['completion_basis'] is None

    verifications = [{
        'finding_id': item['id'], 'outcome': 'VERIFIED',
        'evidence': {'artifact_id': completed['completion_artifact_id'], 'locator': 'completion',
                     'description': 'Local independent verification fixture'},
        'reason': 'The local correction was rechecked'} for item in findings]
    flow.r.mock.configure(rr, verdict, verifications=verifications)
    flow.drive()
    assert flow.task['state'] == ('DONE' if verdict == 'PASS' else 'FINAL_HUMAN_REVIEW')
    assert flow.task['completion_basis'] == ('FINAL_REVIEW_PASS' if verdict == 'PASS' else None)
    assert len(flow.rows('review_requests', review_type='FINAL_REVIEW')) == 2
    assert flow.r.hub.get_review(rr)['request']['review_round'] == 2
    with pytest.raises(HubError):
        ClientGateway(flow.r).invoke('begin_final_fix', begin_fields(flow, findings))
    assert len(flow.rows('review_requests', review_type='FINAL_REVIEW')) == 2


@pytest.mark.parametrize('case', ['stale', 'foreign-finding', 'empty', 'duplicate',
                                  'invalid-scope', 'unknown-field', 'worker', 'human', 'expired'])
def test_gateway_begin_final_fix_rejects_invalid_commands_without_execution(tmp_path, case):
    flow = V2Flow(tmp_path)
    flow.to_final_review('NEEDS_CHANGES')
    fields = begin_fields(flow, flow.r.hub.list_actionable_findings(flow.task_id))
    actor = 'builder'
    if case == 'stale':
        fields['expected_version'] -= 1
    elif case == 'foreign-finding':
        fields['finding_ids'] = ['FND-outside-frozen-final-review']
    elif case == 'empty':
        fields['finding_ids'] = []
    elif case == 'duplicate':
        fields['finding_ids'] *= 2
    elif case == 'invalid-scope':
        fields['proposed_scope'] = {'files': []}
    elif case == 'unknown-field':
        fields['actor_id'] = 'human'
    elif case in ('worker', 'human'):
        actor = 'workbuddy-worker' if case == 'worker' else 'human'
    elif case == 'expired':
        flow.r.clock.advance(86_400)
    before = deepcopy(flow.task)
    assignments = flow.rows('worker_assignments')
    findings = flow.r.hub.list_findings(flow.task_id)
    with pytest.raises(HubError):
        ClientGateway(flow.r, actor).invoke('begin_final_fix', fields)
    assert flow.task == before
    assert flow.rows('worker_assignments') == assignments
    assert flow.r.hub.list_findings(flow.task_id) == findings


def test_gateway_scope_escape_keeps_existing_replan_and_budget_guards(tmp_path):
    flow = V2Flow(tmp_path)
    flow.to_final_review('NEEDS_CHANGES')
    fields = begin_fields(flow, flow.r.hub.list_actionable_findings(flow.task_id))
    fields['proposed_scope'] = {'files': ['outside.py']}
    assignments = flow.rows('worker_assignments')
    response = ClientGateway(flow.r).invoke('begin_final_fix', fields)
    assert response['status'] == 'PLAN_CHANGE_REQUIRED'
    assert flow.task['state'] == 'PLANNING' and flow.task['approved_scope'] is None
    assert flow.rows('worker_assignments') == assignments
    assert flow.task['plan_limit'] == flow.task['final_limit'] == 2
    assert review_counts(flow) == (1, 1)


def test_v2_fix_without_begin_does_not_implicitly_execute(tmp_path):
    flow = V2Flow(tmp_path)
    flow.to_final_review('NEEDS_CHANGES')
    finding = flow.r.hub.list_actionable_findings(flow.task_id)[0]
    gateway = ClientGateway(flow.r)
    gateway.invoke('respond_to_review', respond_fields(flow, finding, 'accept'))
    evidence = flow.artifact('EVIDENCE')
    before = deepcopy(flow.task)
    assignments = flow.rows('worker_assignments')
    with pytest.raises(HubError, match='Begin the matching remediation'):
        gateway.invoke('respond_to_review', respond_fields(flow, finding, 'fix', evidence['id']))
    assert flow.task == before and flow.rows('worker_assignments') == assignments
    assert flow.r.hub.list_actionable_findings(flow.task_id)[0]['status'] == 'ACCEPTED'


def test_v2_final_fix_cannot_mark_a_finding_outside_the_active_subset(tmp_path):
    flow = V2Flow(tmp_path)
    findings = three_final_findings(flow)
    gateway = ClientGateway(flow.r)
    for finding in findings:
        gateway.invoke('respond_to_review', respond_fields(flow, finding, 'accept'))
    gateway.invoke('begin_final_fix', begin_fields(flow, findings[:1]))
    completed = flow.complete_worker()
    before = deepcopy(flow.task)
    with pytest.raises(HubError, match='outside the active Final fix scope'):
        gateway.invoke('respond_to_review', respond_fields(
            flow, findings[1], 'fix', completed['completion_artifact_id']))
    assert flow.task == before
    assert flow.r.hub.list_actionable_findings(flow.task_id)[1]['status'] == 'ACCEPTED'


@pytest.mark.anyio
@pytest.mark.parametrize('case', ['empty-ids', 'null-scope', 'nested-extra', 'empty-scope', 'actor'])
async def test_mcp_begin_final_fix_strict_schema_does_not_silently_discard_inputs(tmp_path, case):
    flow = V2Flow(tmp_path)
    flow.to_final_review('NEEDS_CHANGES')
    fields = begin_fields(flow, flow.r.hub.list_actionable_findings(flow.task_id))
    if case == 'empty-ids':
        fields['finding_ids'] = []
    elif case == 'null-scope':
        fields['proposed_scope'] = None
    elif case == 'nested-extra':
        fields['proposed_scope']['extra_budget'] = 1
    elif case == 'empty-scope':
        fields['proposed_scope'] = {}
    elif case == 'actor':
        fields['actor_id'] = 'human'
    before = snapshot(flow)
    async with Client(create_mcp_server(flow.r), mode='legacy', raise_exceptions=False) as client:
        assert (await client.call_tool('begin_final_fix', fields)).is_error
    assert snapshot(flow) == before
