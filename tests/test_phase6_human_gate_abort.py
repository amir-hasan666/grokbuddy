"""Phase 6 Step 6.5 Human Gate/Abort probes; disposable Hub only, no network."""

from copy import deepcopy

import pytest
from mcp import Client

from grokbuddy.application.common import uid
from grokbuddy.domain.model import Conflict, HubError, PermissionDenied, TriggerNotFound
from grokbuddy.interfaces.gateway import ClientGateway
from grokbuddy.interfaces.mcp import create_mcp_server
from test_phase6_pack_b import V2Flow, event_for, key
from test_phase6_trigger_gate import counts, create, signed_evidence


class LegacyV2Flow(V2Flow):
    """Disposable fixture representing a Task created before the V1 policy freeze."""

    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        with self.r.db.transaction() as repo:
            task = repo.get('tasks', self.task_id)
            task.pop('decision_policy_version', None)
            task.pop('decision_policy_snapshot', None)
            task['plan_limit'] = 2
            task['final_limit'] = 3
            repo.save('tasks', task)


def _plan_gate(flow):
    flow.plan()
    first = flow.request(scenario='NEEDS_CHANGES')
    flow.drive()
    finding = flow.r.hub.list_actionable_findings(flow.task_id, first)[0]
    flow.r.hub.respond_finding(flow.owner, finding['id'], 'accept', None,
                               flow.version, key())
    flow.plan('Human Gate revised Plan')
    evidence = flow.artifact('DIFF', 'Plan Gate correction')
    flow.r.hub.respond_finding(flow.owner, finding['id'], 'fix', evidence['id'],
                               flow.version, key())
    second = flow.request(scenario='NEEDS_CHANGES')
    flow.drive()
    assert flow.task['state'] == 'PLAN_HUMAN_REVIEW'
    return second


def _final_gate(flow):
    flow.to_final_review('NEEDS_CHANGES')
    for _ in range(2):
        flow.fix_current_open_finding()
        flow.package()
        request_id = flow.request('FINAL_REVIEW', 'NEEDS_CHANGES')
        flow.drive()
    assert flow.task['state'] == 'FINAL_HUMAN_REVIEW'
    return request_id


def _unresolved(flow):
    return sorted(item['id'] for item in flow.r.hub.list_actionable_findings(flow.task_id))


def test_plan_gate_accept_is_cas_idempotent_and_keeps_review_immutable(tmp_path):
    flow = LegacyV2Flow(tmp_path / 'plan-accept')
    request_id = _plan_gate(flow)
    original_review = deepcopy(flow.r.hub.get_review(request_id))
    expected_version = flow.version
    command_key = key()
    params = dict(acknowledged_findings=_unresolved(flow))
    accepted = flow.r.hub.human_gate_decide(
        'human', flow.task_id, 'ACCEPT', 'Accept the bounded frozen Plan',
        expected_version, command_key, **params)
    assert accepted['task']['state'] == 'PLAN_APPROVED'
    assert accepted['task']['automation_frozen'] is False
    assert accepted['task']['approved_plan_id'] == accepted['task']['current_plan_id']
    assert accepted['task']['completion_basis'] is None
    assert flow.r.hub.get_review(request_id) == original_review
    assert flow.r.hub.human_gate_decide(
        'human', flow.task_id, 'ACCEPT', 'Accept the bounded frozen Plan',
        expected_version, command_key, **params) == accepted
    with pytest.raises(Conflict, match='Stale task version'):
        flow.r.hub.human_gate_decide(
            'human', flow.task_id, 'ACCEPT', 'stale command', expected_version,
            key(), acknowledged_findings=params['acknowledged_findings'])
    with pytest.raises(HubError, match='not awaiting a Human Gate'):
        flow.r.hub.human_gate_decide(
            'human', flow.task_id, 'ACCEPT', 'illegal state command', flow.version,
            key(), acknowledged_findings=params['acknowledged_findings'])
    with pytest.raises(PermissionDenied):
        flow.r.hub.human_gate_decide(
            flow.owner, flow.task_id, 'ACCEPT', 'agent cannot decide',
            flow.version, key(), acknowledged_findings=params['acknowledged_findings'])
    approvals = flow.rows('human_approvals', task_id=flow.task_id)
    assert approvals[-1]['kind'] == 'PLAN_OVERRIDE'
    assert approvals[-1]['scope']['related_review_request_id'] == request_id


def test_plan_gate_continue_grants_audited_bounded_round(tmp_path):
    flow = LegacyV2Flow(tmp_path / 'plan-continue')
    _plan_gate(flow)
    with pytest.raises(HubError, match='configured Human hard limit'):
        flow.r.hub.human_gate_decide(
            'human', flow.task_id, 'CONTINUE', 'This exceeds the configured cap',
            flow.version, key(), extra_review_budget=3,
            new_deadline_at=flow.r.clock.now() + 120_000_000)
    continued = flow.r.hub.human_gate_decide(
        'human', flow.task_id, 'CONTINUE', 'Allow exactly one additional Plan review',
        flow.version, key(), extra_review_budget=1,
        new_deadline_at=flow.r.clock.now() + 120_000_000)
    assert continued['task']['state'] == 'PLANNING'
    assert continued['task']['plan_limit'] == 3
    assert continued['task']['plan_extra_budget'] == 1
    assert continued['task']['automation_frozen'] is False
    third = flow.r.hub.request_review(
        flow.owner, flow.task_id, 'PLAN_REVIEW', 'mock-reviewer', flow.version, key())
    assert flow.r.hub.get_review(third['review_request_id'])['request']['review_round'] == 3
    budgets = [item for item in flow.rows('human_approvals', task_id=flow.task_id)
               if item['kind'] == 'HUMAN_REVIEW_BUDGET']
    assert budgets[-1]['scope']['granted_budget'] == 1
    assert budgets[-1]['scope']['total_extra_budget'] == 1
    assert budgets[-1]['scope']['hard_extra_limit'] == 2


def test_plan_gate_modify_binds_scope_and_requires_explicit_budget(tmp_path):
    flow = LegacyV2Flow(tmp_path / 'plan-modify')
    _plan_gate(flow)
    selected = _unresolved(flow)
    with pytest.raises(HubError, match='explicit Human review budget'):
        flow.r.hub.human_gate_decide(
            'human', flow.task_id, 'MODIFY', 'Modify within the named file only',
            flow.version, key(), modification_scope={'files': ['local.txt']},
            finding_ids=selected)
    modified = flow.r.hub.human_gate_decide(
        'human', flow.task_id, 'MODIFY', 'Modify within the named file only',
        flow.version, key(), modification_scope={'files': ['local.txt']},
        finding_ids=selected, extra_review_budget=1)
    assert modified['task']['state'] == 'PLANNING'
    assert modified['task']['human_modification_scope'] == {'files': ['local.txt']}
    outside = flow.artifact('PLAN', 'Plan outside Human scope')
    with pytest.raises(HubError, match='Human-specified modification scope'):
        flow.r.hub.submit_plan(
            flow.owner, flow.task_id, outside['id'], flow.version, key(),
            approved_scope={'files': ['outside.txt']})


def test_final_gate_accept_sets_human_override_and_preserves_verdict(tmp_path):
    flow = LegacyV2Flow(tmp_path / 'final-accept')
    request_id = _final_gate(flow)
    original = deepcopy(flow.r.hub.get_review(request_id))
    accepted = flow.r.hub.human_gate_decide(
        'human', flow.task_id, 'ACCEPT', 'Accept qualified package with known findings',
        flow.version, key(), acknowledged_findings=_unresolved(flow))
    task = accepted['task']
    assert task['state'] == 'DONE'
    assert task['completion_basis'] == 'HUMAN_OVERRIDE'
    assert task['completion_actor_id'] == 'human'
    assert task['completion_related_rr_id'] == request_id
    assert task['completion_reason_artifact_id']
    assert task['grokbuddy_enabled'] is False
    assert flow.r.hub.get_review(request_id) == original
    assert original['review']['effective_verdict'] == 'NEEDS_CHANGES'
    assert flow.r.hub.get_conversation_context(task['conversation_id']) == {
        'grokbuddy_enabled': False, 'task_id': None}


def test_final_gate_continue_and_modify_leave_via_declared_edges(tmp_path):
    continued_flow = LegacyV2Flow(tmp_path / 'final-continue')
    _final_gate(continued_flow)
    continued = continued_flow.r.hub.human_gate_decide(
        'human', continued_flow.task_id, 'CONTINUE',
        'Allow one more review of the unchanged Final package',
        continued_flow.version, key(), extra_review_budget=1,
        new_deadline_at=continued_flow.r.clock.now() + 120_000_000)
    assert continued['task']['state'] == 'SELF_TESTING'
    assert continued['task']['final_limit'] == 4
    fourth = continued_flow.r.hub.request_review(
        continued_flow.owner, continued_flow.task_id, 'FINAL_REVIEW', 'mock-reviewer',
        continued_flow.version, key())
    assert continued_flow.r.hub.get_review(
        fourth['review_request_id'])['request']['review_round'] == 4

    modified_flow = LegacyV2Flow(tmp_path / 'final-modify')
    _final_gate(modified_flow)
    selected = _unresolved(modified_flow)
    modified = modified_flow.r.hub.human_gate_decide(
        'human', modified_flow.task_id, 'MODIFY',
        'Repair only the reviewed local file findings', modified_flow.version, key(),
        modification_scope={'files': ['local.txt']}, finding_ids=selected,
        extra_review_budget=1)
    assert modified['task']['state'] == 'EXECUTING'
    assert modified['assignment']['status'] == 'OFFERED'
    assert modified['assignment']['finding_ids'] == selected
    assert modified['task']['active_fix_scope'] == {'files': ['local.txt']}
    assert modified['assignment']['approved_scope'] == modified['task']['approved_scope']


def test_final_gate_out_of_scope_modify_returns_to_plan_without_assignment(tmp_path):
    flow = LegacyV2Flow(tmp_path / 'final-replan')
    _final_gate(flow)
    before = len(flow.rows('worker_assignments', task_id=flow.task_id))
    modified = flow.r.hub.human_gate_decide(
        'human', flow.task_id, 'MODIFY', 'Scope expansion requires a new Plan review',
        flow.version, key(), modification_scope={'files': ['outside.py']},
        finding_ids=_unresolved(flow))
    assert modified['task']['state'] == 'PLANNING'
    assert modified['task']['approved_plan_id'] is None
    assert modified['task']['scope_change_request'] == {'files': ['outside.py']}
    assert modified['assignment'] is None
    assert len(flow.rows('worker_assignments', task_id=flow.task_id)) == before


@pytest.mark.anyio
async def test_plan_gate_abort_via_mcp_clears_context_and_is_not_sticky(tmp_path):
    flow = LegacyV2Flow(tmp_path / 'plan-abort-mcp')
    _plan_gate(flow)
    conversation_id = flow.task['conversation_id']
    before = counts(flow.r)
    async with Client(create_mcp_server(flow.r), mode='legacy', raise_exceptions=True) as client:
        result = (await client.call_tool('human_gate_decide', {
            'task_id': flow.task_id,
            'decision': 'ABORT',
            'reason': 'User aborted the gated Plan',
            'expected_version': flow.version,
            'idempotency_key': key(),
        })).structured_content
    assert result['task']['state'] == 'CANCELLED'
    assert result['task']['grokbuddy_enabled'] is False
    assert flow.r.hub.get_conversation_context(conversation_id) == {
        'grokbuddy_enabled': False, 'task_id': None}
    body, evidence = signed_evidence(
        flow.r, [{'source': 'user_body', 'text': '这是中止后的普通消息'}],
        conversation_id=conversation_id,
        key=b'phase6-pack-b-isolated-trigger-key-32-bytes')
    with pytest.raises(TriggerNotFound):
        create(flow.r, body, evidence)
    after = counts(flow.r)
    assert after[0] == before[0]


def test_final_gate_abort_cancels_pending_outbox_and_stops_loop(tmp_path):
    flow = LegacyV2Flow(tmp_path / 'final-abort')
    request_id = _final_gate(flow)
    with flow.r.db.transaction() as repo:
        outbox = repo.find('outbox_events', review_request_id=request_id)[0]
        outbox.update(status='READY', lease_token=None, next_attempt_at=flow.r.clock.now())
        repo.save('outbox_events', outbox)
    aborted = flow.r.hub.human_gate_decide(
        'human', flow.task_id, 'ABORT', 'Cancel the Final Gate task',
        flow.version, key())
    assert aborted['task']['state'] == 'CANCELLED'
    assert flow.rows('outbox_events', review_request_id=request_id)[0]['status'] == 'CANCELLED'
    assert flow.r.dispatcher.dispatch_one() is None
    assert flow.r.timeouts.sweep() == 0


def test_gate_freeze_blocks_dispatch_worker_and_callback_progress(tmp_path):
    flow = LegacyV2Flow(tmp_path / 'freeze-negative')
    request_id = _final_gate(flow)
    before_task = deepcopy(flow.task)
    before_jobs = len(flow.rows('mock_jobs'))
    with flow.r.db.transaction() as repo:
        request = repo.get('review_requests', request_id)
        request['status'] = 'PENDING'
        repo.save('review_requests', request)
        outbox = repo.find('outbox_events', review_request_id=request_id)[0]
        outbox.update(status='READY', lease_token=None, next_attempt_at=flow.r.clock.now())
        repo.save('outbox_events', outbox)
        completed = max(repo.find('worker_assignments', task_id=flow.task_id),
                        key=lambda item: item['generation'])
        offered = {**completed, 'id': uid('WA'), 'generation': completed['generation'] + 1,
                   'status': 'OFFERED', 'version': 0, 'worker_principal_id': None,
                   'lease_token': None, 'lease_until': 0,
                   'completion_artifact_id': None, 'completion_hash': None,
                   'completed_by': None, 'completed_at': None}
        repo.add('worker_assignments', offered)

    assert flow.r.dispatcher.dispatch_one() is None
    assert flow.rows('outbox_events', review_request_id=request_id)[0]['status'] == 'CANCELLED'
    assert len(flow.rows('mock_jobs')) == before_jobs
    assert not [item for item in flow.r.hub.list_available_worker_tasks('workbuddy-worker')
                if item['task_id'] == flow.task_id]
    with pytest.raises(Conflict, match='not available to claim'):
        flow.r.hub.claim_task('workbuddy-worker', flow.task_id, 0, key())
    with flow.r.db.transaction() as repo:
        claimed = repo.get('worker_assignments', offered['id'])
        claimed.update(status='CLAIMED', version=1,
                       worker_principal_id='workbuddy-worker', claimed_at=flow.r.clock.now(),
                       lease_token=uid('LEASE'), lease_generation=1,
                       lease_until=before_task['deadline_at'])
        repo.save('worker_assignments', claimed)
    with pytest.raises(PermissionDenied, match='assignment is not executable'):
        ClientGateway(flow.r, 'workbuddy-worker').invoke('submit_artifact', {
            'task_id': flow.task_id, 'artifact_type': 'EVIDENCE',
            'content_text': 'must not upload while gated', 'idempotency_key': key()})
    with pytest.raises(PermissionDenied, match='not active'):
        flow.r.hub.report_worker_progress(
            'workbuddy-worker', flow.task_id, 'must not progress while gated', key())
    previous_artifact = completed['completion_artifact_id']
    with pytest.raises(Conflict, match='awaiting completion'):
        flow.r.hub.complete_worker_task(
            'workbuddy-worker', flow.task_id, previous_artifact, 1, key())
    late = event_for(flow, request_id, {'protocol_version': 'v2'},
                     dedup='step65-late-start', kind='ReviewStarted')
    flow.r.events.ingest(late)
    assert flow.r.events.handle_one() == 'LATE_EVENT'
    assert flow.task == before_task
    flow.r.clock.advance(flow.r.settings.max_task_duration + 1)
    assert flow.r.timeouts.sweep() == 0
    assert flow.task['state'] == 'FINAL_HUMAN_REVIEW'


def test_close_task_cancels_active_assignment_outside_gate(tmp_path):
    flow = V2Flow(tmp_path / 'cancel-active-assignment')
    flow.approve_plan()
    assignment = flow.begin_execution()
    cancelled = flow.r.hub.cancel(
        'human', flow.task_id, 'Cancel active implementation', flow.version, key())
    assert cancelled['state'] == 'CANCELLED'
    stored = flow.rows('worker_assignments', id=assignment['id'])[0]
    assert stored['status'] == 'CANCELLED'
    assert stored['lease_token'] is None
    assert cancelled['grokbuddy_enabled'] is False
