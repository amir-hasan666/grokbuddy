"""Offline contract tests. Synthetic ReviewResult here is never a live Grok run."""

import hashlib
import json

import httpx2
import pytest

from conftest import Flow
from grokbuddy.adapters.github import FileGitHubCommentTransport
from grokbuddy.application.common import uid
from grokbuddy.domain.model import Conflict, HubError
from grokbuddy.interfaces.composite import create_composite_application
from grokbuddy.interfaces.grok_reviewer import GrokReviewerApplication


B_ACTOR = 'grok-reviewer-b'
AGENT_ID = '4335c388-584c-434e-b14e-13964b176b6e'
SERVER_ID = '3504754'
TOKEN = 'test-only-dedicated-reviewer-token'


def prepare(flow, tmp_path):
    flow.executing()
    flow.package()
    flow.r.github_bindings.bind_pull_request(
        repository_id=1372874264, repository_full_name='example/grokbuddy',
        pull_request_number=4, task_id=flow.id, hub_pointer_base='hub://test')
    old_rr = flow.request('FINAL_REVIEW')
    flow.h.register_reviewer('system', B_ACTOR, 'workbuddy审核员', AGENT_ID, SERVER_ID)
    route = flow.h.route_future_reviews('builder', flow.id, B_ACTOR, flow.version, flow.key())
    transport = FileGitHubCommentTransport(tmp_path / 'comments.json')
    worker = flow.r.grok_dispatcher(transport, B_ACTOR, 'https://reviewer.example.test')
    return old_rr, route, transport, worker


def resume_as_grok(flow, old_rr):
    flow.r.clock.advance(flow.r.settings.final_review_timeout)
    assert flow.r.timeouts.sweep() == 1
    old_version = flow.version
    key = flow.key()
    args = ('human', 'builder', flow.id, old_rr, 3,
            flow.r.clock.now() + 80_000_000_000,
            'Offline test: new Reviewer B evaluation', old_version, key)
    receipt = flow.h.retry_final_with_grok(*args)
    assert flow.h.retry_final_with_grok(*args) == receipt
    return receipt['review_request_id']


def synthetic_event(flow, rr):
    envelope = flow.h.get_review(rr)['request']['envelope']
    result = {k: envelope[k] for k in (
        'protocol_version', 'task_id', 'review_request_id', 'review_id',
        'review_type', 'review_round', 'content_revision', 'review_profile',
        'review_profile_version', 'profile_sha256', 'input_sha256')}
    result.update(verdict='PASS', summary='Synthetic offline contract fixture',
                  reviewer={'type': 'grok_bot', 'id': B_ACTOR},
                  timestamp='2026-09-20T06:00:00Z', findings=[], verifications=[])
    return dict(event_id=uid('EVT'), event_type='ReviewCompleted', source='grok_bot',
                task_id=flow.id, review_request_id=rr, review_id=envelope['review_id'],
                correlation_id=rr, deduplication_key=rr + ':test-result', payload=result,
                execution={'agent_id': AGENT_ID, 'server_id': SERVER_ID,
                           'run_id': 'offline-test-run-1'})


def test_registration_route_and_dispatch_keep_mock_rr_frozen(flow, tmp_path):
    old_rr, route, transport, worker = prepare(flow, tmp_path)
    old = flow.h.get_review(old_rr)['request']
    assert old['envelope']['expected_reviewer_actor_id'] == 'mock-reviewer'
    assert route['applies_to'] == 'FUTURE_REQUESTS_ONLY'
    assert worker.dispatch_one() is None
    assert not transport._load()['comments']
    assert flow.rows('outbox_events', review_request_id=old_rr)[0]['status'] == 'READY'
    assert flow.h.route_future_reviews('builder', flow.id, B_ACTOR, flow.version,
                                       'route-replay') == route
    with pytest.raises(Conflict):
        flow.h.register_reviewer('system', B_ACTOR, 'another name', AGENT_ID, SERVER_ID)

    new_rr = resume_as_grok(flow, old_rr)
    assert new_rr != old_rr
    assert flow.h.get_review(old_rr)['request']['status'] == 'TIMED_OUT'
    assert flow.h.get_review(new_rr)['request']['envelope']['expected_reviewer_actor_id'] == B_ACTOR
    assert flow.r.dispatcher.dispatch_one() is None
    assert worker.dispatch_one() == 'SENT'
    assert worker.dispatch_one() is None
    comments = transport._load()['comments']
    assert len(comments) == 1
    assert f'<!-- grokbuddy-grok-request:{new_rr} -->' in comments[0]['body']
    assert 'request_pointer=https://reviewer.example.test/reviewer/requests/' in comments[0]['body']
    assert not flow.rows('mock_jobs', id=new_rr)
    assert flow.rows('outbox_events', review_request_id=old_rr)[0]['status'] == 'CANCELLED'
    assert worker.adapter.get_delivery_status(new_rr).status == 'ACCEPTED'
    assert any(a['action'] == 'GROK_REVIEWER_ROUTE_CREATED' for a in flow.rows('audit_logs', task_id=flow.id))


@pytest.mark.anyio
async def test_authenticated_writeback_correlation_replay_and_artifact_scope(flow, tmp_path):
    old_rr, _, transport, worker = prepare(flow, tmp_path)
    new_rr = resume_as_grok(flow, old_rr)
    assert worker.dispatch_one() == 'SENT'
    app = create_composite_application(
        flow.r, 'test-webhook-secret', 'test-mcp-token',
        grok_reviewer_app=GrokReviewerApplication(flow.r, worker.adapter, TOKEN))
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app),
                                  base_url='https://reviewer.example.test') as client:
        path = f'/reviewer/requests/{new_rr}'
        assert (await client.get(path)).status_code == 401
        headers = {'authorization': 'Bearer ' + TOKEN}
        request = await client.get(path, headers=headers)
        assert request.status_code == 200
        profile_id = request.json()['envelope']['profile_artifact_id']
        artifact = await client.get(path + '/artifacts/' + profile_id, headers=headers)
        assert artifact.status_code == 200
        assert hashlib.sha256(artifact.content).hexdigest() == artifact.headers['x-content-sha256']
        assert (await client.get(path + '/artifacts/ART-outside', headers=headers)).status_code == 403
        assert (await client.get(f'/reviewer/requests/{old_rr}', headers=headers)).status_code == 403

        event = synthetic_event(flow, new_rr)
        assert (await client.post('/reviewer/events', json=event)).status_code == 401
        wrong = json.loads(json.dumps(event))
        wrong['execution']['agent_id'] = '00000000-0000-0000-0000-000000000000'
        assert (await client.post('/reviewer/events', json=wrong, headers=headers)).status_code == 422
        forged = json.loads(json.dumps(event))
        forged['review_request_id'] = old_rr
        forged['review_id'] = flow.h.get_review(old_rr)['request']['review_id']
        assert (await client.post('/reviewer/events', json=forged, headers=headers)).status_code == 403
        assert not flow.rows('inbox_events', review_request_id=new_rr)

        wrong_correlation = json.loads(json.dumps(event))
        wrong_correlation['correlation_id'] = old_rr
        wrong_correlation['deduplication_key'] += ':wrong-correlation'
        assert (await client.post('/reviewer/events', json=wrong_correlation, headers=headers)).status_code == 202
        assert flow.r.events.handle_one() == 'REJECTED'

        receipt = await client.post('/reviewer/events', json=event, headers=headers)
        assert receipt.status_code == 202
        assert receipt.json()['status'] == 'READY'
        assert flow.task['state'] == 'FINAL_REVIEW_PENDING'
        assert flow.r.events.handle_one() == 'APPLIED'
        review = flow.h.get_review(new_rr)['review']
        assert review['reviewer_actor_id'] == B_ACTOR
        assert review['execution_identity'] == event['execution']
        assert flow.task['state'] == 'DONE'
        inbox_count = len(flow.rows('inbox_events'))
        result_artifact_count = len(flow.rows('artifacts', artifact_type='REVIEW_RESULT'))
        assert (await client.post('/reviewer/events', json=event, headers=headers)).status_code == 202
        assert flow.r.events.handle_one() is None
        assert len(flow.rows('inbox_events')) == inbox_count
        assert len(flow.rows('artifacts', artifact_type='REVIEW_RESULT')) == result_artifact_count
        conflicting_run = json.loads(json.dumps(event))
        conflicting_run['event_id'] = uid('EVT')
        conflicting_run['execution']['run_id'] = 'offline-test-run-2'
        assert (await client.post('/reviewer/events', json=conflicting_run, headers=headers)).status_code == 422
        assert flow.r.events.handle_one() is None
        assert len(flow.rows('reviews', review_request_id=new_rr)) == 1
        assert flow.h.get_review(old_rr)['review'] is None
        assert flow.h.get_review(old_rr)['request']['status'] == 'TIMED_OUT'
        assert any(a['action'] == 'REVIEW_COMPLETED' and a['actor_id'] == B_ACTOR
                   for a in flow.rows('audit_logs', task_id=flow.id))
        flow.r.github_projections.enqueue_final_review(new_rr)
        assert flow.r.github_projections.project_one(transport) in ('CREATE', 'CREATED')
        assert flow.r.github_projections.project_one(transport) is None
        assert len(transport._load()['comments']) == 2  # request pointer + final projection
        assert len(flow.rows('github_comment_projections')) == 1


def test_grok_adapter_refuses_unrouted_mock_and_non_https(runtime, tmp_path):
    flow = Flow(runtime)
    flow.plan()
    old_rr = flow.request()
    runtime.hub.register_reviewer('system', B_ACTOR, 'workbuddy审核员', AGENT_ID, SERVER_ID)
    with pytest.raises(HubError, match='HTTPS'):
        runtime.grok_dispatcher(FileGitHubCommentTransport(tmp_path / 'c.json'),
                                B_ACTOR, 'http://example.test')
    worker = runtime.grok_dispatcher(FileGitHubCommentTransport(tmp_path / 'c.json'),
                                     B_ACTOR, 'https://example.test')
    assert worker.dispatch_one() is None
    with pytest.raises(HubError, match='not routed'):
        worker.adapter.get_delivery_status(old_rr)


def test_future_signed_github_event_selects_registered_reviewer_b(flow):
    flow.executing()
    flow.package()
    flow.r.github_bindings.bind_pull_request(
        repository_id=1372874264, repository_full_name='example/grokbuddy',
        pull_request_number=4, task_id=flow.id)
    flow.h.register_reviewer('system', B_ACTOR, 'workbuddy审核员', AGENT_ID, SERVER_ID)
    flow.h.route_future_reviews('builder', flow.id, B_ACTOR, flow.version, flow.key())
    event = dict(event_name='pull_request', action='synchronize',
                 repository_id=1372874264, repository_full_name='example/grokbuddy',
                 resource_type='pull_request', resource_id='4',
                 resource_revision='a' * 40, pull_request_number=4,
                 sender_id=12345, canonical_key='github:1372874264:pull_request:4:synchronize:' + 'a' * 40,
                 advances_final_review=True)
    receipt = flow.r.github_events.ingest(delivery_id='grok-route-test-1',
                                          event_name='pull_request', raw_sha256='b' * 64,
                                          event=event)
    rr = flow.h.get_review(receipt['effect']['review_request_id'])['request']
    assert rr['envelope']['expected_reviewer_actor_id'] == B_ACTOR
    assert rr['status'] == 'PENDING'
