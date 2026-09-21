import pytest
from conftest import Flow, CONTRACTS
from grokbuddy.infrastructure.runtime import LocalRuntime
from grokbuddy.infrastructure.clock import ManualClock
from grokbuddy.domain.model import Settings, HubError
from test_events import event_for


def test_accumulated_findings_are_not_a_task_count_limit(tmp_path):
    r = LocalRuntime(tmp_path, CONTRACTS, clock=ManualClock(),
                     settings=Settings(max_findings_per_review=1), legacy_create_test_mode=True)
    flow = Flow(r); flow.executing()
    for _ in range(2):
        flow.package(); flow.request('FINAL_REVIEW', 'NEEDS_CHANGES'); flow.drive()
    assert flow.task['total_findings_created'] == 2
    assert flow.task['state'] == 'FINAL_CHANGES_REQUIRED'


def test_finding_changes_cannot_race_active_evaluation(flow):
    flow.executing(); flow.package(); flow.request('FINAL_REVIEW','NEEDS_CHANGES'); flow.drive()
    finding = flow.h.list_findings(flow.id)[0]
    flow.package(); flow.request('FINAL_REVIEW')
    with pytest.raises(HubError):
        flow.h.respond_finding('builder', finding['id'], 'accept', None, flow.version, flow.key())
    with pytest.raises(HubError):
        flow.h.waive_finding('human', finding['id'], 'Cannot alter frozen evaluation', flow.version, flow.key())


def test_duplicate_new_finding_key_rejects_whole_event(flow):
    flow.executing(); flow.package(); rr = flow.request('FINAL_REVIEW')
    result = flow.r.mock._result(flow.h.get_review(rr)['request']['envelope'], {'scenario':'NEEDS_CHANGES'})
    result['findings'] *= 2
    flow.r.events.ingest(event_for(flow, rr, result))
    assert flow.r.events.handle_one() == 'REJECTED'
    assert not flow.h.list_findings(flow.id)


def test_unrelated_reviewer_identity_rejected(flow):
    with flow.r.db.transaction() as repo:
        repo.add('actors', dict(id='other-reviewer', name='other-reviewer', role='REVIEWER',
                 provider_id='local:other-reviewer', reviewer_type='mock', enabled=True))
    flow.plan(); rr = flow.request()
    event = event_for(flow, rr, actor='other-reviewer')
    event.payload['reviewer']['id'] = 'other-reviewer'
    flow.r.events.ingest(event)
    assert flow.r.events.handle_one() == 'REJECTED'
    assert not flow.rows('reviews')


def test_live_context_cannot_be_changed_during_review(flow):
    flow.plan(); rr = flow.request()
    artifact = flow.artifact('PLAN', 'New content during pending review')
    with pytest.raises(HubError):
        flow.h.submit_plan('builder', flow.id, artifact['id'], flow.version, flow.key())
    assert flow.h.get_review(rr)['request']['envelope']['input_artifact_id'] != artifact['id']


def test_approval_guard_is_rechecked_in_final_event_handler(flow):
    flow.executing(); flow.package(); rr = flow.request('FINAL_REVIEW')
    # A persistent guard remains effective even if a new hold is injected by a trusted host.
    with flow.r.db.transaction() as repo:
        repo.add('human_approvals', dict(id='guard-fixture', task_id=flow.id, kind='HIGH_RISK_ACTION', status='PENDING'))
    flow.r.events.ingest(event_for(flow, rr))
    assert flow.r.events.handle_one() == 'REJECTED'
    assert flow.task['state'] == 'FINAL_REVIEW_PENDING'
    assert not flow.rows('reviews', review_request_id=rr)
