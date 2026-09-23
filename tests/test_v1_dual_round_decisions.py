"""V1 decision policy probes against disposable local Hub storage only."""

from copy import deepcopy

import pytest

from grokbuddy.domain.model import HubError
from test_phase6_pack_b import V2Flow, event_for, key


def _result(flow, rr, verdict):
    envelope = flow.r.hub.get_review(rr)['request']['envelope']
    return flow.r.mock._result(envelope, {'scenario': verdict})


def _apply(flow, rr, payload, dedup):
    flow.r.events.ingest(event_for(flow, rr, payload, dedup=dedup))
    return flow.r.events.handle_one()


def _revised_plan(flow, finding_id):
    flow.r.hub.respond_finding(flow.owner, finding_id, 'accept', None, flow.version, key())
    flow.plan('V1 revised plan')
    evidence = flow.artifact('DIFF', 'V1 Plan correction')
    flow.r.hub.respond_finding(flow.owner, finding_id, 'fix', evidence['id'], flow.version, key())
    return evidence


def test_plan_r1_pass_approves_immediately_and_freezes_two_round_policy(tmp_path):
    flow = V2Flow(tmp_path)
    assert flow.task['decision_policy_snapshot'] == {
        'version': 'grokbuddy-v1-dual-round', 'plan_max_rounds': 2, 'final_max_rounds': 2}
    flow.plan()
    rr = flow.request(scenario='PASS')
    request = flow.r.hub.get_review(rr)['request']
    assert request['envelope']['decision_policy_version'] == flow.task['decision_policy_version']
    assert flow.task['state'] == 'PLAN_REVIEW_PENDING'
    with pytest.raises(HubError, match='Task cannot request this review'):
        flow.r.hub.request_review(flow.owner, flow.task_id, 'FINAL_REVIEW',
                                  'mock-reviewer', flow.version, key())
    flow.drive()
    assert flow.task['state'] == 'PLAN_APPROVED'
    assert flow.task['approved_plan_id'] == request['input_artifact_id']
    flow.begin_execution()
    assert len(flow.rows('review_requests', review_type='PLAN_REVIEW')) == 1


@pytest.mark.parametrize('first_verdict', ['NEEDS_CHANGES', 'BLOCK'])
def test_plan_r1_revision_then_r2_pass(first_verdict, tmp_path):
    flow = V2Flow(tmp_path)
    flow.plan()
    first = flow.request(scenario=first_verdict)
    flow.drive()
    assert flow.task['state'] == 'PLAN_CHANGES_REQUIRED'
    assert flow.r.hub.get_review(first)['review']['reported_verdict'] == first_verdict
    finding = flow.r.hub.list_actionable_findings(flow.task_id)[0]
    evidence = _revised_plan(flow, finding['id'])
    second = flow.request(scenario='PASS', findings=[], verifications=[{
        'finding_id': finding['id'], 'outcome': 'VERIFIED',
        'evidence': {'artifact_id': evidence['id'], 'locator': 'plan',
                     'description': 'Correction verified'}, 'reason': 'Plan scope now covers it'}])
    flow.drive()
    assert flow.task['state'] == 'PLAN_APPROVED'
    assert flow.r.hub.get_review(second)['request']['review_round'] == 2
    assert flow.task['revision_round'] == 1


def test_plan_r2_block_human_gate_and_no_third_round_or_plan_override(tmp_path):
    flow = V2Flow(tmp_path)
    flow.plan()
    flow.request(scenario='NEEDS_CHANGES')
    flow.drive()
    finding = flow.r.hub.list_actionable_findings(flow.task_id)[0]
    _revised_plan(flow, finding['id'])
    second = flow.request(scenario='BLOCK')
    flow.drive()
    assert flow.task['state'] == 'PLAN_HUMAN_REVIEW'
    assert flow.r.hub.get_review(second)['review']['effective_verdict'] == 'BLOCK'
    assert flow.task['automation_frozen'] is True
    with pytest.raises(HubError, match='V1 Plan requires a Grok PASS'):
        flow.r.hub.human_gate_decide('human', flow.task_id, 'ACCEPT', 'Do not bypass R2',
                                    flow.version, key(), acknowledged_findings=[finding['id']])
    with pytest.raises(HubError, match='V1 Task cannot extend'):
        flow.r.hub.human_gate_decide('human', flow.task_id, 'CONTINUE', 'Attempt R3',
                                    flow.version, key(), extra_review_budget=1,
                                    new_deadline_at=flow.r.clock.now() + 120_000_000)
    with pytest.raises(HubError, match='third review round'):
        flow.r.hub.resume('human', flow.task_id, 'PLAN_REVIEW', 3,
                          flow.r.clock.now() + 120_000_000, 'Attempt R3', flow.version, key())
    assert len(flow.rows('review_requests', review_type='PLAN_REVIEW')) == 2


def test_final_r1_block_gets_one_fix_and_r2_pass(tmp_path):
    flow = V2Flow(tmp_path)
    first = flow.to_final_review('BLOCK')
    assert flow.task['state'] == 'FINAL_CHANGES_REQUIRED'
    assert flow.r.hub.get_review(first)['review']['reported_verdict'] == 'BLOCK'
    finding_id = flow.fix_current_open_finding()
    flow.package()
    evidence = flow.artifact('DIFF', 'Final fix verified')
    second = flow.request('FINAL_REVIEW', 'PASS', findings=[], verifications=[{
        'finding_id': finding_id, 'outcome': 'VERIFIED',
        'evidence': {'artifact_id': evidence['id'], 'locator': 'code',
                     'description': 'Final correction evidence'}, 'reason': 'Fix verified'}])
    flow.drive()
    assert flow.task['state'] == 'DONE'
    assert flow.task['completion_basis'] == 'FINAL_REVIEW_PASS'
    assert flow.r.hub.get_review(second)['request']['review_round'] == 2


def test_final_r2_block_is_human_gate_and_not_r3(tmp_path):
    flow = V2Flow(tmp_path)
    flow.to_final_review('NEEDS_CHANGES')
    flow.fix_current_open_finding()
    flow.package()
    second = flow.request('FINAL_REVIEW', 'BLOCK')
    flow.drive()
    review = flow.r.hub.get_review(second)
    assert review['request']['status'] == 'COMPLETED'
    assert review['review']['effective_verdict'] == 'BLOCK'
    assert flow.task['state'] == 'FINAL_HUMAN_REVIEW'
    assert flow.task['completion_basis'] is None
    with pytest.raises(HubError, match='V1 Task cannot extend'):
        flow.r.hub.human_gate_decide('human', flow.task_id, 'CONTINUE', 'Attempt R3',
                                    flow.version, key(), extra_review_budget=1,
                                    new_deadline_at=flow.r.clock.now() + 120_000_000)
    assert len(flow.rows('review_requests', review_type='FINAL_REVIEW')) == 2


def test_r2_minor_finding_becomes_auditable_advisory_not_needs_changes(tmp_path):
    flow = V2Flow(tmp_path)
    flow.plan()
    first = flow.request(scenario='NEEDS_CHANGES')
    payload = _result(flow, first, 'NEEDS_CHANGES')
    payload['findings'][0]['severity'] = 'LOW'
    assert _apply(flow, first, payload, 'minor-r1') == 'APPLIED'
    finding = flow.r.hub.list_actionable_findings(flow.task_id)[0]
    _revised_plan(flow, finding['id'])
    second = flow.request(scenario='PASS')
    payload = _result(flow, second, 'PASS')
    payload['recommendations'] = ['Optional wording cleanup; does not affect the Plan direction']
    payload['verifications'] = [{
        'finding_id': finding['id'], 'outcome': 'ADVISORY',
        'evidence': {'artifact_id': flow.task['current_plan_id'], 'locator': 'plan wording',
                     'description': 'Remaining issue is cosmetic only'},
        'reason': 'No impact on scope, safety, data or core requirement'}]
    assert _apply(flow, second, payload, 'minor-r2') == 'APPLIED'
    assert flow.task['state'] == 'PLAN_APPROVED'
    assert flow.r.hub.get_review(second)['review']['effective_verdict'] == 'PASS'
    assert flow.r.hub.list_actionable_findings(flow.task_id) == []
    advised = flow.rows('review_findings', id=finding['id'])[0]
    assert advised['advisory'] is True and advised['actionable'] is False
    assert any(row.get('outcome') == 'ADVISORY' for row in flow.rows('finding_events', finding_id=finding['id']))


def test_r2_invalid_needs_changes_does_not_create_review_or_finding(tmp_path):
    flow = V2Flow(tmp_path)
    flow.plan()
    flow.request(scenario='NEEDS_CHANGES')
    flow.drive()
    finding = flow.r.hub.list_actionable_findings(flow.task_id)[0]
    _revised_plan(flow, finding['id'])
    second = flow.request(scenario='NEEDS_CHANGES')
    before = deepcopy(flow.task)
    payload = _result(flow, second, 'NEEDS_CHANGES')
    assert _apply(flow, second, payload, 'r2-invalid') == 'REJECTED'
    assert flow.task == before
    assert flow.r.hub.get_review(second)['request']['status'] == 'PENDING'
    assert flow.r.hub.get_review(second)['review'] is None
    assert len(flow.rows('review_findings', task_id=flow.task_id)) == 1


def test_r2_pass_with_unverified_substantive_finding_is_rejected(tmp_path):
    flow = V2Flow(tmp_path)
    flow.plan()
    flow.request(scenario='NEEDS_CHANGES')
    flow.drive()
    finding = flow.r.hub.list_actionable_findings(flow.task_id)[0]
    _revised_plan(flow, finding['id'])
    second = flow.request(scenario='PASS')
    assert _apply(flow, second, _result(flow, second, 'PASS'), 'unverified-pass') == 'REJECTED'
    assert flow.r.hub.get_review(second)['review'] is None
    assert flow.task['state'] == 'PLAN_REVIEW_PENDING'


def test_r2_low_only_block_is_rejected_as_non_substantive(tmp_path):
    flow = V2Flow(tmp_path)
    flow.plan()
    first = flow.request(scenario='NEEDS_CHANGES')
    first_payload = _result(flow, first, 'NEEDS_CHANGES')
    first_payload['findings'][0]['severity'] = 'LOW'
    assert _apply(flow, first, first_payload, 'low-first') == 'APPLIED'
    finding = flow.r.hub.list_actionable_findings(flow.task_id)[0]
    _revised_plan(flow, finding['id'])
    second = flow.request(scenario='BLOCK')
    payload = _result(flow, second, 'BLOCK')
    payload['findings'][0]['severity'] = 'LOW'
    assert _apply(flow, second, payload, 'low-block') == 'REJECTED'
    assert flow.r.hub.get_review(second)['review'] is None
    assert flow.task['state'] == 'PLAN_REVIEW_PENDING'


@pytest.mark.parametrize('scenario', ['FAILED', 'TIMEOUT'])
def test_technical_failure_never_becomes_reviewer_block(scenario, tmp_path):
    flow = V2Flow(tmp_path)
    flow.plan()
    rr = flow.request(scenario=scenario)
    flow.drive()
    if scenario == 'TIMEOUT':
        flow.r.clock.advance(flow.r.settings.plan_review_timeout + 1)
        flow.r.tick()
    request = flow.r.hub.get_review(rr)
    assert request['review'] is None
    assert request['request']['status'] in ('FAILED', 'TIMED_OUT')
    assert flow.task['state'] == 'PLAN_HUMAN_REVIEW'
    assert flow.task['gate_reason'] != 'REVIEW_BLOCK'


def test_human_can_continue_after_r1_technical_failure_with_remaining_budget(tmp_path):
    flow = V2Flow(tmp_path)
    flow.plan()
    first = flow.request(scenario='FAILED')
    flow.drive()
    assert flow.r.hub.get_review(first)['review'] is None
    continued = flow.r.hub.human_gate_decide(
        'human', flow.task_id, 'CONTINUE', 'Retry after technical Reviewer failure',
        flow.version, key(), extra_review_budget=0,
        new_deadline_at=flow.r.clock.now() + 120_000_000)
    assert continued['task']['state'] == 'PLANNING'
    assert continued['task']['plan_limit'] == 2
    second = flow.request(scenario='PASS')
    flow.drive()
    assert flow.r.hub.get_review(second)['request']['review_round'] == 2
    assert flow.task['state'] == 'PLAN_APPROVED'
