from copy import deepcopy
import pytest
from grokbuddy.domain.model import HubError
from test_events import event_for


def pending_action(flow, ttl=60):
    flow.executing()
    action = flow.action()
    approval = flow.h.request_action('builder', flow.id, action, ttl, flow.version, flow.key())
    return action, approval


@pytest.mark.parametrize('actor', ['builder', 'mock-reviewer', 'system'])
def test_only_human_can_approve(flow, actor):
    action, approval = pending_action(flow)
    before = flow.task
    with pytest.raises(HubError):
        flow.h.decide_action(actor, approval['id'], True, 'attempted bypass', flow.version, flow.key())
    assert flow.task == before
    assert flow.rows('human_approvals', id=approval['id'])[0]['status'] == 'PENDING'


def test_reviewer_pass_and_override_cannot_bypass_pending_action(flow):
    action, approval = pending_action(flow)
    plan_rr = flow.rows('review_requests')[0]
    assert flow.task['state'] == 'AWAITING_HUMAN_APPROVAL'
    # Replay of a real previously completed PASS must not authorize the dangerous action.
    old_review = flow.h.get_review(plan_rr['id'])['review']
    art = flow.rows('artifacts', id=old_review['result_artifact_id'])[0]
    import json
    payload = json.loads(flow.r.store.read(art['storage_pointer'], art['sha256'], art['size_bytes']))
    flow.r.events.ingest(event_for(flow, plan_rr['id'], payload))
    assert flow.r.events.handle_one() == 'DUPLICATE'
    assert flow.task['state'] == 'AWAITING_HUMAN_APPROVAL'
    with pytest.raises(HubError):
        flow.request('FINAL_REVIEW')
    with pytest.raises(HubError):
        flow.h.override_review('human', flow.id, 'PLAN_REVIEW', flow.task['current_plan_id'], [],
                               'Override is not approval', flow.r.clock.now()+60_000_000, flow.version, flow.key())
    with pytest.raises(HubError):
        flow.h.consume_action('builder', approval['id'], action, flow.version, flow.key())


def test_approval_binding_expiry_and_single_consumption(flow):
    action, approval = pending_action(flow)
    flow.h.decide_action('human', approval['id'], True, 'Approve exact test scope', flow.version, flow.key())
    assert flow.task['state'] == 'EXECUTING'
    changed = deepcopy(action)
    changed['targets'] = ['another-resource']
    with pytest.raises(HubError):
        flow.h.consume_action('builder', approval['id'], changed, flow.version, flow.key())
    # A valid but unconsumed approval cannot be bypassed by moving to final review.
    with pytest.raises(HubError):
        flow.package()
    version, key = flow.version, flow.key()
    receipt = flow.h.consume_action('builder', approval['id'], action, version, key)
    assert receipt['status'] == 'CONSUMED' and receipt['execution_performed'] is False
    assert flow.h.consume_action('builder', approval['id'], action, version, key) == receipt
    with pytest.raises(HubError):
        flow.h.consume_action('builder', approval['id'], action, flow.version, flow.key())
    flow.package(); flow.request('FINAL_REVIEW'); flow.drive()
    assert flow.task['state'] == 'DONE'


def test_approval_expiry_needs_human_resolution(flow):
    action, approval = pending_action(flow, ttl=2)
    flow.h.decide_action('human', approval['id'], True, 'Approve temporarily', flow.version, flow.key())
    flow.r.clock.advance(2)
    with pytest.raises(HubError):
        flow.h.consume_action('builder', approval['id'], action, flow.version, flow.key())
    flow.r.timeouts.sweep()
    assert flow.task['state'] == 'ESCALATED'
    assert flow.rows('human_approvals', id=approval['id'])[0]['status'] == 'EXPIRED'
    flow.h.withdraw_action('human', approval['id'], 'Abandon this unexecuted action', flow.version, flow.key())
    flow.h.resume('human', flow.id, 'PLAN_REVIEW', 3, flow.r.clock.now()+60_000_000,
                  'Design without abandoned action', flow.version, flow.key())
    assert flow.task['state'] == 'PLANNING'
    with pytest.raises(HubError):
        flow.h.consume_action('builder', approval['id'], action, flow.version, flow.key())


def test_task_deadline_does_not_leave_expired_approval_unresolvable(flow):
    action, approval = pending_action(flow, ttl=flow.r.settings.max_task_duration)
    flow.r.clock.advance(flow.r.settings.max_task_duration)
    flow.r.timeouts.sweep()
    assert flow.task['state'] == 'ESCALATED'
    flow.h.withdraw_action('human', approval['id'], 'Abandon expired unexecuted action', flow.version, flow.key())
    flow.h.resume('human', flow.id, 'PLAN_REVIEW', 3, flow.r.clock.now()+60_000_000,
                  'Replan safely', flow.version, flow.key())
    assert flow.task['state'] == 'PLANNING'
    with pytest.raises(HubError):
        flow.h.consume_action('builder', approval['id'], action, flow.version, flow.key())


@pytest.mark.parametrize('target,expected', [('cancel','CANCELLED'), ('replan','PLANNING')])
def test_human_rejection(flow, target, expected):
    action, approval = pending_action(flow)
    flow.h.decide_action('human', approval['id'], False, 'Do not execute', flow.version, flow.key(), reject_to=target)
    assert flow.task['state'] == expected
    assert flow.rows('human_approvals', id=approval['id'])[0]['status'] == 'REJECTED'
    if target == 'replan':
        flow.plan(); flow.request(); flow.drive(); flow.move('execute')
        flow.package(); flow.request('FINAL_REVIEW'); flow.drive()
        assert flow.task['state'] == 'DONE'


def test_final_override_keeps_review_and_findings_immutable(flow):
    flow.executing(); flow.package(); rr = flow.request('FINAL_REVIEW', 'NEEDS_CHANGES'); flow.drive()
    old = flow.h.get_review(rr)['review']
    finding = flow.h.list_findings(flow.id)[0]
    with pytest.raises(HubError):
        flow.h.override_review('human', flow.id, 'FINAL_REVIEW', flow.task['current_final_id'], [],
                               'Missing risk acknowledgment', flow.r.clock.now()+60_000_000, flow.version, flow.key())
    flow.h.override_review('human', flow.id, 'FINAL_REVIEW', flow.task['current_final_id'], [finding['id']],
                           'Explicitly accept this documented risk', flow.r.clock.now()+60_000_000, flow.version, flow.key())
    assert flow.task['state'] == 'DONE'
    assert flow.h.get_review(rr)['review'] == old
    assert flow.h.list_findings(flow.id)[0]['status'] == 'OPEN'
    assert flow.rows('human_approvals', kind='REVIEW_OVERRIDE')


def test_plan_override_does_not_finish_task_and_stops_active_review(flow):
    flow.plan(); rr = flow.request(scenario='TIMEOUT')
    flow.h.override_review('human', flow.id, 'PLAN_REVIEW', flow.task['current_plan_id'], [],
                           'Approve this frozen plan', flow.r.clock.now()+60_000_000, flow.version, flow.key())
    assert flow.task['state'] == 'PLAN_APPROVED'
    assert flow.h.get_review(rr)['request']['status'] == 'ESCALATED'
    assert flow.r.dispatcher.dispatch_one() is None


def test_cancel_never_resurrected_by_late_completion(flow):
    flow.plan(); rr = flow.request()
    flow.h.cancel('human', flow.id, 'User cancelled', flow.version, flow.key())
    flow.r.events.ingest(event_for(flow, rr))
    assert flow.r.events.handle_one() == 'LATE_EVENT'
    assert flow.task['state'] == 'CANCELLED'
    assert flow.r.dispatcher.dispatch_one() is None


@pytest.mark.parametrize('actor', ['builder','mock-reviewer'])
def test_waiver_and_override_not_available_to_agents(flow, actor):
    flow.executing(); flow.package(); flow.request('FINAL_REVIEW','NEEDS_CHANGES'); flow.drive()
    fid = flow.h.list_findings(flow.id)[0]['id']
    with pytest.raises(HubError):
        flow.h.waive_finding(actor, fid, 'Unauthorized waiver', flow.version, flow.key())
    with pytest.raises(HubError):
        flow.h.override_review(actor, flow.id, 'FINAL_REVIEW', flow.task['current_final_id'], [fid],
                               'Unauthorized override', flow.r.clock.now()+60_000_000, flow.version, flow.key())
