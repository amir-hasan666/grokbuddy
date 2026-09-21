from dataclasses import replace
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
import pytest

from grokbuddy.domain.model import HubError, NormalizedEvent
from grokbuddy.application.common import uid


def event_for(flow, rr, payload=None, key=None, actor='mock-reviewer', kind='ReviewCompleted'):
    request = flow.h.get_review(rr)['request']['envelope']
    if payload is None:
        payload = flow.r.mock._result(request, {'scenario': 'PASS'})
    return NormalizedEvent(uid('EVT'), kind, 'mock', actor, flow.id, rr, request['review_id'], rr, key or uid('KEY'), payload)


def test_duplicate_events_apply_once(flow):
    flow.plan(); rr = flow.request(scenario='DUPLICATE_EVENT')
    flow.drive()
    assert len(flow.rows('reviews')) == 1
    assert len(flow.rows('inbox_events')) == 1
    assert flow.rows('inbox_events')[0]['status'] == 'APPLIED'
    assert len(flow.rows('artifacts', artifact_type='REVIEW_RESULT')) == 1
    assert flow.task['state'] == 'PLAN_APPROVED'


def test_duplicate_completion_across_new_ids_and_sources(flow):
    flow.plan(); rr = flow.request()
    event = event_for(flow, rr)
    flow.r.events.ingest(event)
    flow.r.events.ingest(replace(event, event_id=uid('EVT'), source='alternate-local-transport', deduplication_key='another-resource'))
    flow.r.events.handle_one(); flow.r.events.handle_one()
    assert len(flow.rows('reviews')) == 1
    assert flow.rows('inbox_events')[-1]['status'] == 'DUPLICATE'


@pytest.mark.parametrize('same_key', [True, False])
def test_conflicting_completion_cannot_overwrite(flow, same_key):
    flow.plan(); rr = flow.request()
    event = event_for(flow, rr, key='stable-key')
    flow.r.events.ingest(event); flow.r.events.handle_one()
    before = flow.task
    modified = deepcopy(event.payload)
    modified['summary'] = 'Different result for completed review'
    conflicting = replace(event, event_id=uid('EVT'), payload=modified,
                          deduplication_key='stable-key' if same_key else 'new-key')
    if same_key:
        with pytest.raises(HubError, match='Deduplication key reused'):
            flow.r.events.ingest(conflicting)
    else:
        flow.r.events.ingest(conflicting)
        assert flow.r.events.handle_one() == 'REJECTED'
    assert flow.task == before and len(flow.rows('reviews')) == 1


@pytest.mark.parametrize('field,value', [('protocol_version','v2'), ('review_round',99),
    ('content_revision',99),('review_profile','document'),('profile_sha256','c'*64),
    ('input_sha256','c'*64),('verdict','PASSED')])
def test_schema_and_frozen_binding_rejections_do_not_advance(flow, field, value):
    flow.plan(); rr = flow.request()
    event = event_for(flow, rr)
    event.payload[field] = value
    before = flow.task
    flow.r.events.ingest(event)
    assert flow.r.events.handle_one() == 'REJECTED'
    assert flow.task == before and not flow.rows('reviews')
    assert flow.h.get_review(rr)['request']['status'] == 'PENDING'
    assert any(a['action'] == 'VALIDATION_FAILURE' for a in flow.h.audit_log(flow.id))


def test_missing_version_and_bad_reviewer(flow):
    flow.plan(); rr = flow.request()
    event = event_for(flow, rr)
    del event.payload['protocol_version']
    flow.r.events.ingest(event); assert flow.r.events.handle_one() == 'REJECTED'
    event = event_for(flow, rr)
    event.payload['reviewer']['id'] = 'builder'
    flow.r.events.ingest(event); assert flow.r.events.handle_one() == 'REJECTED'
    with pytest.raises(HubError):
        flow.r.events.ingest(replace(event, actor_id='builder'))
    assert not flow.rows('reviews')


def test_started_and_late_started_share_handler(flow):
    flow.plan(); rr = flow.request()
    event = event_for(flow, rr, {'protocol_version': 'v1'}, kind='ReviewStarted')
    flow.r.events.ingest(event)
    assert flow.r.events.handle_one() == 'APPLIED'
    assert flow.task['state'] == 'PLAN_REVIEWING'
    flow.drive()
    assert flow.task['state'] == 'PLAN_APPROVED'
    before = flow.task
    flow.r.events.ingest(replace(event, event_id=uid('EVT'), deduplication_key='late-start'))
    assert flow.r.events.handle_one() == 'LATE_EVENT'
    assert flow.task == before


def test_invalid_mock_payload_and_reported_failure(flow):
    flow.plan(); rr = flow.request(scenario='INVALID_PAYLOAD')
    flow.drive()
    assert flow.task['state'] == 'PLAN_REVIEW_PENDING'
    assert flow.h.get_review(rr)['request']['status'] == 'PENDING'
    assert flow.rows('inbox_events')[0]['status'] == 'REJECTED'


def test_reviewer_failed_event_escalates(flow):
    flow.plan(); rr = flow.request(scenario='FAILED'); flow.drive()
    assert flow.task['state'] == 'ESCALATED'
    assert flow.h.get_review(rr)['request']['status'] == 'FAILED'


def test_plan_pass_with_blocking_risk_rejected(flow):
    flow.plan(); rr = flow.request()
    event = event_for(flow, rr)
    event.payload['risks'] = [{'code':'BLOCKING','description':'Unresolved risk','blocking':True}]
    flow.r.events.ingest(event)
    assert flow.r.events.handle_one() == 'REJECTED'


def test_concurrent_duplicate_handlers(flow):
    flow.plan(); rr = flow.request()
    event = event_for(flow, rr)
    for _ in range(8):
        flow.r.events.ingest(event)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: flow.r.events.handle_one(), range(12)))
    while flow.r.events.handle_one() is not None:
        pass
    assert len(flow.rows('reviews')) == 1
    assert len([e for e in flow.rows('inbox_events') if e['status']=='APPLIED']) == 1


def test_transaction_crash_after_review_insert_rolls_back_all(flow, monkeypatch):
    flow.executing(); flow.package(); rr = flow.request('FINAL_REVIEW', 'NEEDS_CHANGES')
    flow.r.dispatcher.dispatch_one(); flow.r.mock.run_one()
    before = flow.task
    original = flow.r.events._apply_findings
    def crash(*args):
        original(*args)
        raise RuntimeError('Simulated process loss before commit')
    monkeypatch.setattr(flow.r.events, '_apply_findings', crash)
    with pytest.raises(RuntimeError):
        flow.r.events.handle_one()
    assert flow.task == before
    assert not flow.rows('reviews', review_request_id=rr)
    assert not flow.rows('review_findings')
    assert flow.rows('inbox_events')[-1]['status'] == 'READY'
    monkeypatch.setattr(flow.r.events, '_apply_findings', original)
    assert flow.r.events.handle_one() == 'APPLIED'
    assert len(flow.rows('review_findings')) == 1


def test_invalid_json_normalization_rejected(flow):
    with pytest.raises(HubError):
        flow.r.mock.normalize_review_event('{invalid JSON', 'mock-reviewer')
