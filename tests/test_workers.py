from concurrent.futures import ThreadPoolExecutor
import pytest
from conftest import Flow, CONTRACTS
from grokbuddy.domain.model import RetryableDelivery, DeliveryUnknown, DeliveryReceipt, Settings
from grokbuddy.infrastructure.runtime import LocalRuntime
from grokbuddy.infrastructure.clock import ManualClock
from test_events import event_for


class FaultAdapter:
    def __init__(self, mock, error, failures):
        self.mock, self.error, self.failures, self.calls = mock, error, failures, 0

    def get_delivery_status(self, key):
        return self.mock.get_delivery_status(key)

    def submit_review_request(self, envelope, key):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error()
        return self.mock.submit_review_request(envelope, key)


def test_retry_same_request_round_and_no_long_transaction(flow):
    flow.plan(); rr = flow.request()
    adapter = FaultAdapter(flow.r.mock, RetryableDelivery, 1)
    flow.r.dispatcher.adapter = adapter
    assert flow.r.dispatcher.dispatch_one() == 'RETRY'
    assert not flow.rows('mock_jobs')
    assert flow.r.dispatcher.dispatch_one() is None
    flow.r.clock.advance(1)
    assert flow.r.dispatcher.dispatch_one() == 'SENT'
    assert adapter.calls == 2
    assert len(flow.rows('review_requests')) == len(flow.rows('review_rounds')) == 1
    flow.r.mock.run_one(); flow.r.events.handle_one()
    assert flow.h.get_review(rr)['request']['review_round'] == 1


def test_retry_exhaustion_stops_all_automatic_calls(flow):
    flow.plan(); rr = flow.request()
    adapter = FaultAdapter(flow.r.mock, RetryableDelivery, 100)
    flow.r.dispatcher.adapter = adapter
    for _ in range(flow.r.settings.delivery_max_attempts):
        flow.r.dispatcher.dispatch_one()
        flow.r.clock.advance(1)
    assert flow.task['state'] == 'ESCALATED'
    assert flow.h.get_review(rr)['request']['status'] == 'FAILED'
    for _ in range(3):
        assert flow.r.dispatcher.dispatch_one() is None
    assert adapter.calls == 5


def test_ambiguous_delivery_escalates_without_blind_resend(flow):
    flow.plan(); rr = flow.request()
    adapter = FaultAdapter(flow.r.mock, DeliveryUnknown, 1)
    flow.r.dispatcher.adapter = adapter
    assert flow.r.dispatcher.dispatch_one() == 'UNKNOWN'
    assert flow.task['state'] == 'ESCALATED'
    flow.r.clock.advance(60)
    assert flow.r.dispatcher.dispatch_one() is None
    assert adapter.calls == 1


def test_dispatch_crash_after_acceptance_reconciles_existing_job(flow):
    flow.plan(); rr = flow.request()
    row, request = flow.r.dispatcher._claim()
    flow.r.mock.submit_review_request(request['envelope'], row['delivery_key'])
    # Simulated process crash: outbox lease is still outstanding; job is durable.
    flow.r.clock.advance(flow.r.settings.lease_seconds)
    restarted = LocalRuntime(flow.r.directory, CONTRACTS, clock=flow.r.clock)
    assert restarted.dispatcher.dispatch_one() == 'SENT'
    assert len(flow.rows('mock_jobs')) == 1
    restarted.mock.run_one(); restarted.events.handle_one()
    assert flow.task['state'] == 'PLAN_APPROVED'


def test_mock_job_lease_recovers_without_a_special_state_path(flow):
    flow.plan(); flow.request()
    flow.r.dispatcher.dispatch_one()
    assert flow.r.queue.take() is not None
    assert flow.r.mock.run_one() is None
    flow.r.clock.advance(flow.r.settings.lease_seconds)
    assert flow.r.mock.run_one() == 'PASS'
    assert flow.task['state'] == 'PLAN_REVIEW_PENDING'
    flow.r.events.handle_one()
    assert flow.task['state'] == 'PLAN_APPROVED'


def test_two_dispatchers_claim_one_job(flow):
    flow.plan(); flow.request()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: flow.r.dispatcher.dispatch_one(), range(2)))
    assert len(flow.rows('mock_jobs')) == 1
    assert flow.rows('outbox_events')[0]['attempts'] == 1


def test_timeout_preserves_rr_and_late_result_cannot_revive(flow):
    flow.plan(); rr = flow.request(scenario='TIMEOUT'); flow.drive()
    flow.r.clock.advance(flow.r.settings.plan_review_timeout)
    assert flow.r.timeouts.sweep() == 1
    assert flow.h.get_review(rr)['request']['status'] == 'TIMED_OUT'
    assert flow.task['state'] == 'ESCALATED'
    flow.r.events.ingest(event_for(flow, rr))
    assert flow.r.events.handle_one() == 'LATE_EVENT'
    assert not flow.rows('reviews')
    assert flow.r.dispatcher.dispatch_one() is None


def test_completion_exactly_at_deadline_loses_without_scheduler(flow):
    flow.plan(); rr = flow.request()
    flow.r.events.ingest(event_for(flow, rr))
    flow.r.clock.advance(flow.r.settings.plan_review_timeout)
    assert flow.r.events.handle_one() == 'LATE_EVENT'
    assert flow.h.get_review(rr)['request']['status'] == 'TIMED_OUT'


def test_timeout_completion_race_serializes(flow):
    flow.plan(); rr = flow.request()
    flow.r.events.ingest(event_for(flow, rr))
    flow.r.clock.advance(flow.r.settings.plan_review_timeout)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(flow.r.timeouts.sweep)
        b = pool.submit(flow.r.events.handle_one)
        a.result(); b.result()
    assert flow.task['state'] == 'ESCALATED'
    assert not flow.rows('reviews')


@pytest.mark.parametrize('final_outcome,expected', [('PASS','PLAN_APPROVED'), ('NEEDS_CHANGES','ESCALATED')])
def test_plan_last_round_boundary(flow, final_outcome, expected):
    flow.plan(); flow.request(scenario='NEEDS_CHANGES'); flow.drive()
    flow.plan(); flow.request(scenario=final_outcome); flow.drive()
    assert flow.task['state'] == expected
    assert len(flow.rows('review_requests')) == 2


@pytest.mark.parametrize('final_outcome,expected', [('PASS','DONE'), ('NEEDS_CHANGES','ESCALATED')])
def test_final_last_round_boundary(flow, final_outcome, expected):
    flow.executing()
    for index in range(3):
        flow.package()
        scenario = final_outcome if index == 2 else 'NEEDS_CHANGES'
        # Reviewer may request more work without findings; final strict verdict still applies.
        flow.request('FINAL_REVIEW', scenario, findings=[])
        flow.drive()
    assert flow.task['state'] == expected
    assert len(flow.rows('review_requests', review_type='FINAL_REVIEW')) == 3


def test_max_task_duration_is_persisted_and_includes_waiting(tmp_path):
    clock = ManualClock()
    runtime = LocalRuntime(tmp_path, CONTRACTS, clock=clock,
                           settings=Settings(max_task_duration=5), legacy_create_test_mode=True)
    flow = Flow(runtime)
    deadline = flow.task['deadline_at']
    restarted = LocalRuntime(tmp_path, CONTRACTS, clock=clock)
    clock.advance(5)
    assert restarted.timeouts.sweep() == 1
    assert flow.task['deadline_at'] == deadline
    assert flow.task['state'] == 'ESCALATED'


def test_explicit_human_resume_extends_budget_without_resetting_rounds(flow):
    for _ in range(2):
        flow.plan(); flow.request(scenario='NEEDS_CHANGES'); flow.drive()
    assert flow.task['state'] == 'ESCALATED'
    flow.h.resume('human', flow.id, 'PLAN_REVIEW', 3, flow.r.clock.now()+60_000_000,
                  'One additional evaluation authorized', flow.version, flow.key())
    flow.plan(); rr = flow.request(); flow.drive()
    assert flow.h.get_review(rr)['request']['review_round'] == 3
    assert flow.task['state'] == 'PLAN_APPROVED'
