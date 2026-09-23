"""Pack D P01-P12 probes; disposable SQLite/artifacts and mock transports only."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import json

import httpx2
import pytest

from conftest import CONTRACTS
from grokbuddy.domain.model import (Conflict, DeliveryReceipt, NormalizedEvent,
                                    PermissionDenied)
from grokbuddy.infrastructure.runtime import LocalRuntime
from grokbuddy.interfaces.gateway import ClientGateway
from grokbuddy.interfaces.grok_reviewer import GrokReviewerApplication
from test_phase6_pack_b import TRIGGER_KEY, V2Flow, event_for, key


def rows(runtime, table, **filters):
    with runtime.db.transaction() as repo:
        return repo.find(table, **filters)


def approve_plan(flow, supervisor=None):
    supervisor = supervisor or flow.r.supervisor()
    flow.plan()
    request_id = flow.request()
    supervisor.run_until_idle()
    assert flow.task['state'] == 'PLAN_APPROVED'
    return request_id, supervisor


def claim_assignment(flow):
    offered = [item for item in flow.r.hub.list_available_worker_tasks('workbuddy-worker')
               if item['task_id'] == flow.task_id][0]
    return flow.r.hub.claim_task('workbuddy-worker', flow.task_id,
                                 offered['version'], key())


def worker_artifact(flow, text='Pack D worker evidence'):
    return ClientGateway(flow.r, 'workbuddy-worker').invoke('submit_artifact', {
        'task_id': flow.task_id, 'artifact_type': 'EVIDENCE',
        'content_text': text, 'idempotency_key': key(),
    })


def complete_worker(flow):
    claimed = claim_assignment(flow)
    artifact = worker_artifact(flow)
    progress = flow.r.hub.report_worker_progress(
        'workbuddy-worker', flow.task_id, 'Pack D bounded progress', key())
    completed = flow.r.hub.complete_worker_task(
        'workbuddy-worker', flow.task_id, artifact['id'], progress['version'], key())
    return claimed, completed


def test_p01_duplicate_claim_and_stale_generation_are_fenced(tmp_path):
    flow = V2Flow(tmp_path / 'p01')
    approve_plan(flow)
    flow.begin_execution()
    offered = flow.rows('worker_assignments', task_id=flow.task_id)[-1]

    def attempt(command_key):
        try:
            return flow.r.hub.claim_task(
                'workbuddy-worker', flow.task_id, offered['version'], command_key)
        except Conflict:
            return 'CONFLICT'

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, [key(), key()]))
    assert sum(isinstance(item, dict) for item in outcomes) == 1
    assert outcomes.count('CONFLICT') == 1
    claimed = [item for item in outcomes if isinstance(item, dict)][0]

    flow.r.clock.advance(flow.r.settings.lease_seconds + 1)
    assert flow.r.timeouts.recover_assignments() == 1
    assignments = flow.rows('worker_assignments', task_id=flow.task_id)
    assert [(item['generation'], item['status']) for item in assignments] == [
        (1, 'FROZEN'), (2, 'OFFERED')]
    with pytest.raises(Conflict, match='Stale record or lease'):
        with flow.r.db.transaction() as repo:
            repo.compare_and_swap('worker_assignments',
                                  {**claimed, 'status': 'COMPLETED', 'version': 2},
                                  {'status': 'CLAIMED',
                                   'lease_generation': claimed['lease_generation']})
    assert len(flow.rows('tasks')) == 1
    assert len(flow.rows('review_requests')) == 1


def test_p02_duplicate_worker_completion_replays_once_and_conflicts_on_change(tmp_path):
    flow = V2Flow(tmp_path / 'p02')
    approve_plan(flow)
    flow.begin_execution()
    claim_assignment(flow)
    first_artifact = worker_artifact(flow, 'first immutable completion')
    second_artifact = worker_artifact(flow, 'different immutable completion')
    progress = flow.r.hub.report_worker_progress(
        'workbuddy-worker', flow.task_id, 'ready to complete', key())
    command_key = key()
    args = ('workbuddy-worker', flow.task_id, first_artifact['id'],
            progress['version'], command_key)
    completed = flow.r.hub.complete_worker_task(*args)
    assert flow.r.hub.complete_worker_task(*args) == completed
    with pytest.raises(Conflict, match='different input'):
        flow.r.hub.complete_worker_task(
            'workbuddy-worker', flow.task_id, second_artifact['id'],
            progress['version'], command_key)
    audits = [item for item in flow.rows('audit_logs', task_id=flow.task_id)
              if item['action'] == 'WORKER_ASSIGNMENT_COMPLETED']
    assert len(audits) == 1
    assert flow.task['state'] == 'EXECUTING'


def test_p03_duplicate_callback_cross_source_and_conflicting_key(tmp_path):
    flow = V2Flow(tmp_path / 'p03')
    flow.plan()
    request_id = flow.request(scenario='NEEDS_CHANGES')
    assert flow.r.dispatcher.dispatch_one() == 'SENT'
    assert flow.r.mock.run_one(request_id) == 'NEEDS_CHANGES'
    incoming = flow.rows('inbox_events', review_request_id=request_id)[0]
    artifact = flow.rows('artifacts', id=incoming['payload_artifact_id'])[0]
    payload = json.loads(flow.r.store.read(
        artifact['storage_pointer'], artifact['sha256'], artifact['size_bytes']))
    event = NormalizedEvent(
        event_id=incoming['event_id'], event_type=incoming['event_type'],
        source=incoming['source'], actor_id=incoming['actor_id'], task_id=incoming['task_id'],
        review_request_id=request_id, review_id=incoming['review_id'],
        correlation_id=incoming['correlation_id'],
        deduplication_key=incoming['deduplication_key'], payload=payload,
        execution_identity=incoming.get('execution_identity'))
    before_artifacts = len(flow.rows('artifacts'))
    assert flow.r.events.ingest(event) == incoming['id']
    cross_ingress = flow.r.events.ingest(replace(
        event, source='mock-poll', deduplication_key='cross-mode-result'))
    assert cross_ingress != incoming['id']
    assert len(flow.rows('artifacts')) == before_artifacts
    changed = deepcopy(payload)
    changed['summary'] = 'conflicting payload for the same key'
    with pytest.raises(Conflict):
        flow.r.events.ingest(replace(event, payload=changed))
    assert flow.r.events.handle_one() == 'APPLIED'
    assert flow.r.events.handle_one() == 'DUPLICATE'
    assert len(flow.rows('reviews', review_request_id=request_id)) == 1
    assert len(flow.rows('review_findings', task_id=flow.task_id)) == 1


def test_p04_hub_restart_recovers_committed_outbox_and_inbox_exactly_once(tmp_path):
    directory = tmp_path / 'p04'
    flow = V2Flow(directory)
    flow.plan()
    request_id = flow.request()
    restarted = LocalRuntime(directory, CONTRACTS, clock=flow.r.clock,
                             trigger_source_key=TRIGGER_KEY)
    restarted.supervisor().run_until_idle()
    assert restarted.hub.get_task(flow.task_id)['state'] == 'PLAN_APPROVED'
    assert len(rows(restarted, 'review_requests', task_id=flow.task_id)) == 1
    assert len(rows(restarted, 'reviews', review_request_id=request_id)) == 1

    second = V2Flow(tmp_path / 'p04-inbox')
    second.plan()
    second_rr = second.request()
    assert second.r.dispatcher.dispatch_one() == 'SENT'
    second.r.mock.run_one(second_rr)
    after_ingress = LocalRuntime(second.r.directory, CONTRACTS, clock=second.r.clock,
                                 trigger_source_key=TRIGGER_KEY)
    after_ingress.supervisor().run_until_idle()
    after_apply = LocalRuntime(second.r.directory, CONTRACTS, clock=second.r.clock,
                               trigger_source_key=TRIGGER_KEY)
    after_apply.supervisor().run_until_idle()
    assert len(rows(after_apply, 'reviews', review_request_id=second_rr)) == 1
    assert rows(after_apply, 'inbox_events', review_request_id=second_rr)[0]['status'] == 'APPLIED'


def test_p04b_two_task_interleaved_duplicate_restart_apply_isolated(tmp_path):
    directory = tmp_path / 'p04b-two-task-isolation'
    task_a = V2Flow(directory)
    task_a.plan()
    task_b = V2Flow(directory)

    def snapshot(task_id):
        with task_a.r.db.transaction() as repo:
            requests = repo.find('review_requests', task_id=task_id)
            request_ids = {item['id'] for item in requests}
            return {
                'task': deepcopy(repo.get('tasks', task_id)),
                'review_requests': requests,
                'review_rounds': repo.find('review_rounds', task_id=task_id),
                'reviews': repo.find('reviews', task_id=task_id),
                'findings': repo.find('review_findings', task_id=task_id),
                'artifacts': repo.find('artifacts', task_id=task_id),
                'assignments': repo.find('worker_assignments', task_id=task_id),
                'audit': repo.find('audit_logs', task_id=task_id),
                'events': repo.find('task_events', task_id=task_id),
                'outbox': [item for item in repo.find('outbox_events')
                           if item['review_request_id'] in request_ids],
                'inbox': [item for item in repo.find('inbox_events')
                          if item['task_id'] == task_id],
            }

    before_b = snapshot(task_b.task_id)
    assert before_b['task']['state'] == 'NEW'
    command_key = key()
    request_args = (
        task_a.owner, task_a.task_id, 'PLAN_REVIEW', 'mock-reviewer',
        task_a.version, command_key)
    first = task_a.r.hub.request_review(*request_args)
    assert task_a.r.hub.request_review(*request_args) == first
    request_id = first['review_request_id']
    task_a.r.mock.configure(request_id, 'PASS')
    assert task_a.r.dispatcher.dispatch_one() == 'SENT'
    assert task_a.r.mock.run_one(request_id) == 'PASS'

    restarted = LocalRuntime(
        directory, CONTRACTS, clock=task_a.r.clock,
        trigger_source_key=TRIGGER_KEY)
    assert restarted.events.handle_one() == 'APPLIED'
    assert restarted.events.handle_one() is None

    after_b = snapshot(task_b.task_id)
    assert after_b == before_b
    assert restarted.hub.get_task(task_b.task_id)['state'] == 'NEW'
    assert len(rows(restarted, 'review_requests', task_id=task_a.task_id)) == 1
    assert len(rows(restarted, 'review_rounds', task_id=task_a.task_id)) == 1
    assert len(rows(restarted, 'reviews', task_id=task_a.task_id)) == 1
    assert len(rows(restarted, 'outbox_events', review_request_id=request_id)) == 1
    receipts = [item for item in rows(restarted, 'command_receipts')
                if item['operation'] == 'request_review'
                and item['response'].get('review_request_id') == request_id]
    assert len(receipts) == 1
    assert restarted.hub.get_task(task_a.task_id)['state'] == 'PLAN_APPROVED'


def test_p05_worker_restart_recovers_expired_lease_without_late_completion(tmp_path):
    flow = V2Flow(tmp_path / 'p05')
    approve_plan(flow)
    flow.begin_execution()
    claimed = claim_assignment(flow)
    evidence = worker_artifact(flow)
    progress = flow.r.hub.report_worker_progress(
        'workbuddy-worker', flow.task_id, 'progress before simulated crash', key())
    flow.r.clock.advance(flow.r.settings.lease_seconds + 1)
    restarted = LocalRuntime(flow.r.directory, CONTRACTS, clock=flow.r.clock,
                             trigger_source_key=TRIGGER_KEY)
    restarted.supervisor().tick()
    assignments = rows(restarted, 'worker_assignments', task_id=flow.task_id)
    assert [(item['generation'], item['status']) for item in assignments] == [
        (1, 'FROZEN'), (2, 'OFFERED')]
    with pytest.raises(PermissionDenied, match='test-only'):
        restarted.hub.complete_worker_task(
            'workbuddy-worker', flow.task_id, evidence['id'], progress['version'], key())
    assert claimed['lease_generation'] == 1
    assert restarted.hub.get_task(flow.task_id)['state'] == 'EXECUTING'


def test_p06_reviewer_timeout_enters_plan_gate_without_fake_revision(tmp_path):
    flow = V2Flow(tmp_path / 'p06')
    flow.plan()
    request_id = flow.request(scenario='TIMEOUT')
    supervisor = flow.r.supervisor()
    supervisor.run_until_idle()
    assert flow.task['state'] == 'PLAN_REVIEW_PENDING'
    flow.r.clock.advance(flow.r.settings.plan_review_timeout + 1)
    supervisor.run_until_idle()
    request = flow.r.hub.get_review(request_id)['request']
    assert request['status'] == 'TIMED_OUT'
    assert flow.task['state'] == 'PLAN_HUMAN_REVIEW'
    assert flow.task['revision_round'] == 0
    assert not flow.rows('reviews', review_request_id=request_id)
    assert not flow.rows('review_findings', task_id=flow.task_id)

    class InterruptedNetwork:
        def get_delivery_status(self, _delivery_key):
            return DeliveryReceipt('UNKNOWN')

        def submit_review_request(self, *_args):
            raise AssertionError('unknown delivery must be reconciled before submit')

    interrupted = V2Flow(tmp_path / 'p06-network')
    interrupted.plan()
    network_rr = interrupted.request()
    interrupted.r.dispatcher.adapter = InterruptedNetwork()
    network_supervisor = interrupted.r.supervisor()
    for _ in range(interrupted.r.settings.delivery_max_attempts):
        network_supervisor.run_until_idle()
        interrupted.r.clock.advance(100)
    assert interrupted.task['state'] == 'PLAN_HUMAN_REVIEW'
    assert interrupted.r.hub.get_review(network_rr)['request']['status'] == 'FAILED'
    assert interrupted.task['revision_round'] == 0
    assert not interrupted.rows('mock_jobs', id=network_rr)

    class ReconciledNetwork:
        def __init__(self):
            self.statuses = ['UNKNOWN', 'ACCEPTED']
            self.submit_calls = 0

        def get_delivery_status(self, _delivery_key):
            return DeliveryReceipt(self.statuses.pop(0))

        def submit_review_request(self, *_args):
            self.submit_calls += 1
            return DeliveryReceipt('ACCEPTED')

    reconciled = V2Flow(tmp_path / 'p06-reconciled')
    reconciled.plan()
    reconciled_rr = reconciled.request()
    adapter = ReconciledNetwork()
    reconciled.r.dispatcher.adapter = adapter
    assert reconciled.r.dispatcher.dispatch_one() == 'UNKNOWN'
    reconciled.r.clock.advance(2)
    assert reconciled.r.dispatcher.dispatch_one() == 'SENT'
    assert adapter.submit_calls == 0
    assert reconciled.rows('outbox_events', review_request_id=reconciled_rr)[0]['status'] == 'SENT'


class AmbiguousProjectionTransport:
    def __init__(self):
        self.comments = []
        self.create_calls = 0

    def find_comment(self, _binding, marker):
        return next((dict(item) for item in self.comments if marker in item['body']), None)

    def create_comment(self, _binding, body):
        self.create_calls += 1
        self.comments.append({'id': 'pack-d-comment', 'body': body,
                              'url': 'https://example.test/comment'})
        error = TimeoutError('ambiguous create receipt')
        error.code = 'TIMEOUT'
        error.retryable = True
        raise error

    def update_comment(self, _binding, comment_id, body):
        raise AssertionError('reconcile must reuse the marker comment')


def test_p07_projection_unknown_reconciles_without_rolling_back_hub_or_double_comment(tmp_path):
    flow = V2Flow(tmp_path / 'p07')
    transport = AmbiguousProjectionTransport()

    def policy(task):
        return dict(repository_id=7007, repository_full_name='isolated/pack-d',
                    pull_request_number=7, reviewer_actor_id='mock-reviewer',
                    hub_pointer_base='hub://pack-d') if task['id'] == flow.task_id else None

    supervisor = flow.r.supervisor(projection_transport=transport, binding_policy=policy)
    approve_plan(flow, supervisor)
    flow.begin_execution()
    complete_worker(flow)
    flow.package()
    final_rr = flow.request('FINAL_REVIEW')
    supervisor.run_until_idle()
    assert flow.task['state'] == 'DONE'
    assert flow.r.hub.get_review(final_rr)['request']['status'] == 'COMPLETED'
    projection = flow.rows('github_comment_projections', review_request_id=final_rr)[0]
    assert projection['status'] == 'UNKNOWN'
    assert len(transport.comments) == transport.create_calls == 1
    flow.r.clock.advance(2)
    supervisor.run_until_idle()
    projection = flow.rows('github_comment_projections', review_request_id=final_rr)[0]
    assert projection['status'] == 'SENT'
    assert projection['comment_id'] == 'pack-d-comment'
    assert len(transport.comments) == transport.create_calls == 1
    assert flow.task['state'] == 'DONE'


def test_p08_same_idempotency_key_same_hash_returns_original_receipt(runtime):
    command_key = key()
    task = runtime.hub.create_task('builder', 'Pack D idempotency replay', command_key)
    assert runtime.hub.create_task('builder', 'Pack D idempotency replay', command_key) == task
    reviewer_id = 'pack-d-reviewer'
    runtime.hub.register_reviewer(
        'system', reviewer_id, 'Pack D Reviewer',
        '80080000-0000-4000-8000-000000000008', '8008')

    def policy(candidate):
        return dict(repository_id=8008, repository_full_name='isolated/replay',
                    pull_request_number=8, reviewer_actor_id=reviewer_id,
                    hub_pointer_base='hub://pack-d') if candidate['id'] == task['id'] else None

    supervisor = runtime.supervisor(binding_policy=policy)
    supervisor.run_until_idle()
    supervisor.run_until_idle()
    assert len(rows(runtime, 'tasks')) == 1
    assert len(rows(runtime, 'artifacts', task_id=task['id'])) == 1
    assert len(rows(runtime, 'github_bindings', task_id=task['id'])) == 1
    assert len(rows(runtime, 'grok_reviewer_routes', task_id=task['id'])) == 1


def test_p09_same_idempotency_key_different_hash_is_rejected_without_business_mutation(runtime):
    task = runtime.hub.create_task('builder', 'Pack D original command', key())
    command_key = key()
    runtime.hub.submit_artifact(
        'builder', task['id'], 'EVIDENCE', b'original evidence', command_key)
    before = (len(rows(runtime, 'tasks')), len(rows(runtime, 'artifacts')))
    with pytest.raises(Conflict, match='different input'):
        runtime.hub.submit_artifact(
            'builder', task['id'], 'EVIDENCE', b'changed evidence', command_key)
    assert (len(rows(runtime, 'tasks')), len(rows(runtime, 'artifacts'))) == before
    assert runtime.hub.get_task(task['id'])['state'] == 'NEW'
    assert any(item['action'] == 'COMMAND_REJECTED' for item in rows(runtime, 'audit_logs'))


def test_p10_gate_freeze_cancels_dispatch_and_quarantines_late_event(tmp_path):
    flow = V2Flow(tmp_path / 'p10')
    flow.plan()
    request_id = flow.request(scenario='TIMEOUT')
    supervisor = flow.r.supervisor()
    supervisor.run_until_idle()
    flow.r.clock.advance(flow.r.settings.plan_review_timeout + 1)
    supervisor.run_until_idle()
    gated = deepcopy(flow.task)
    with flow.r.db.transaction() as repo:
        outbox = repo.find('outbox_events', review_request_id=request_id)[0]
        outbox.update(status='READY', next_attempt_at=flow.r.clock.now(), lease_token=None)
        repo.save('outbox_events', outbox)
    late = event_for(flow, request_id, {'protocol_version': 'v2'},
                     dedup='p10-late-start', kind='ReviewStarted')
    flow.r.events.ingest(late)
    supervisor.run_until_idle()
    assert flow.rows('outbox_events', review_request_id=request_id)[0]['status'] == 'CANCELLED'
    assert flow.rows('inbox_events', deduplication_key='p10-late-start')[0]['status'] == 'LATE_EVENT'
    assert flow.task == gated
    assert len(flow.rows('review_requests', task_id=flow.task_id)) == 1


def test_p11_one_task_runs_plan_worker_final_to_done_under_supervisor(tmp_path):
    flow = V2Flow(tmp_path / 'p11')
    supervisor = flow.r.supervisor()
    plan_rr, _ = approve_plan(flow, supervisor)
    flow.begin_execution()
    _, completed = complete_worker(flow)
    assert completed['task_state'] == 'EXECUTING'
    assert flow.task['state'] == 'EXECUTING'
    flow.package()
    final_rr = flow.request('FINAL_REVIEW')
    supervisor.run_until_idle()
    assert flow.task['state'] == 'DONE'
    assert {item['task_id'] for item in flow.rows('review_requests')} == {flow.task_id}
    assert [flow.r.hub.get_review(rr)['request']['review_type']
            for rr in (plan_rr, final_rr)] == ['PLAN_REVIEW', 'FINAL_REVIEW']
    assert len(flow.rows('tasks')) == 1


@pytest.mark.anyio
async def test_p12_token_rotation_overlap_then_revocation_has_no_hub_mutation(tmp_path):
    class Adapter:
        reviewer_actor_id = 'mock-reviewer'

    runtime = LocalRuntime(tmp_path / 'p12', CONTRACTS, legacy_create_test_mode=True)
    application = GrokReviewerApplication(runtime, Adapter(), ['old-token', 'new-token'])
    before = (len(rows(runtime, 'tasks')), len(rows(runtime, 'review_requests')),
              len(rows(runtime, 'inbox_events')))
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=application),
                                  base_url='https://reviewer.example.test') as client:
        assert (await client.get('/not-found', headers={
            'authorization': 'Bearer old-token'})).status_code == 404
        assert (await client.get('/not-found', headers={
            'authorization': 'Bearer new-token'})).status_code == 404
        application.replace_tokens('new-token')
        assert (await client.get('/not-found', headers={
            'authorization': 'Bearer old-token'})).status_code == 401
        assert (await client.get('/not-found', headers={
            'authorization': 'Bearer new-token'})).status_code == 404
    assert (len(rows(runtime, 'tasks')), len(rows(runtime, 'review_requests')),
            len(rows(runtime, 'inbox_events'))) == before
    assert 'old-token' not in json.dumps(rows(runtime, 'audit_logs'))
