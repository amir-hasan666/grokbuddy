"""Isolated proof for the optional Reviewer webhook wake path."""

import json
from pathlib import Path
from uuid import uuid4

import pytest

from conftest import CONTRACTS
from grokbuddy.adapters.github import FileGitHubCommentTransport
from grokbuddy.adapters.reviewer_wake import ReviewerWakeHttpTransport
from grokbuddy.application.trigger import PHRASE, issue_trigger_evidence
from grokbuddy.domain.model import HubError
from grokbuddy.infrastructure.clock import ManualClock
from grokbuddy.infrastructure.runtime import LocalRuntime
from grokbuddy.interfaces.gateway import ClientGateway
from scripts import grokbuddy_composite


B_ACTOR = 'grok-reviewer-b'
TRIGGER_KEY = b'phase6-reviewer-wake-local-key-32-bytes'


def _register_b(runtime):
    runtime.hub.register_reviewer(
        'system', B_ACTOR, 'workbuddy reviewer',
        '4335c388-584c-434e-b14e-13964b176b6e', '3504754')


def _http_review(runtime):
    unique = str(uuid4())
    message = {
        'principal_id': 'workbuddy-ingress',
        'conversation_id': 'phase6-wake-' + unique,
        'message_id': str(uuid4()),
        'turn_id': str(uuid4()),
        'message_role': 'user',
        'issued_at': runtime.clock.now(),
        'segments': [{
            'source': 'user_body',
            'text': PHRASE + '，创建 Reviewer webhook wake 隔离测试。',
        }],
    }
    body, evidence = issue_trigger_evidence(
        message, TRIGGER_KEY, runtime.clock.now())
    ingress = ClientGateway(runtime, 'workbuddy-ingress')
    builder = ClientGateway(runtime, 'builder')
    created = ingress.invoke('create_task', {
        'description': body,
        'idempotency_key': str(uuid4()),
        'trigger_evidence': evidence,
    })
    plan = builder.invoke('submit_artifact', {
        'task_id': created['id'],
        'artifact_type': 'PLAN',
        'content_text': 'Reviewer webhook wake local fixture',
        'idempotency_key': str(uuid4()),
    })
    planned = builder.invoke('submit_plan', {
        'task_id': created['id'],
        'plan_artifact_id': plan['id'],
        'approved_scope': {'summary': 'wake only', 'files': ['local.txt']},
        'expected_version': created['version'],
        'idempotency_key': str(uuid4()),
    })
    request_id = builder.invoke('request_plan_review', {
        'task_id': planned['id'],
        'expected_version': planned['version'],
        'idempotency_key': str(uuid4()),
    })['review_request_id']
    return planned['id'], request_id


def _runtime_and_supervisor(tmp_path, wake_transport=None, *, max_attempts=3):
    runtime = LocalRuntime(
        tmp_path / 'reviewer-wake', CONTRACTS, clock=ManualClock(),
        trigger_source_key=TRIGGER_KEY,
        default_reviewer_actor_id=B_ACTOR,
    )
    _register_b(runtime)
    task_id, request_id = _http_review(runtime)
    intake = runtime.grok_intake(B_ACTOR)
    comment_transport = FileGitHubCommentTransport(tmp_path / 'unused-comments.json')
    dispatcher = runtime.grok_dispatcher(
        comment_transport, B_ACTOR, 'https://grokbuddy.amirhasan.top',
        intake=intake)
    reviewer_wake = (
        runtime.grok_reviewer_wake(
            B_ACTOR, wake_transport, max_attempts=max_attempts)
        if wake_transport is not None else None
    )
    supervisor = runtime.supervisor(
        projection_transport=comment_transport,
        binding_policy=lambda _task: None,
        dispatcher=dispatcher,
        intake=intake,
        reviewer_wake=reviewer_wake,
    )
    return runtime, task_id, request_id, supervisor


class RecordingWakeTransport:
    def __init__(self, failure=None):
        self.calls = []
        self.failure = failure
        self.before_send = None

    def send(self, request_id, deduplication_key):
        if self.before_send is not None:
            self.before_send(request_id)
        self.calls.append((request_id, deduplication_key))
        if self.failure is not None:
            raise self.failure
        return 200


class SyntheticWakeError(Exception):
    def __init__(self, *, retryable, code='WAKE_TEST_FAILURE', http_status_code=None):
        self.code = code
        self.retryable = retryable
        self.http_status_code = http_status_code


def test_sent_http_intake_triggers_one_deduplicated_wake(tmp_path):
    wake = RecordingWakeTransport()
    runtime, _, request_id, supervisor = _runtime_and_supervisor(tmp_path, wake)

    def assert_pullable_before_post(actual_request_id):
        with runtime.db.transaction() as repo:
            assert repo.find(
                'outbox_events', review_request_id=actual_request_id)[0]['status'] == 'SENT'
            assert repo.find(
                'intake_receipts', source='grok-reviewer-http',
                review_request_id=actual_request_id)[0]['status'] == 'READY'

    wake.before_send = assert_pullable_before_post

    first = supervisor.tick()
    second = supervisor.tick()

    assert first['dispatch'] == 'SENT'
    assert first['reviewer_wake'] == 'ACKED'
    assert second['reviewer_wake'] is None
    assert len(wake.calls) == 1
    assert wake.calls[0][0] == request_id
    with runtime.db.transaction() as repo:
        outbox = repo.find('outbox_events', review_request_id=request_id)[0]
        intake = repo.find(
            'intake_receipts', source='grok-reviewer-http',
            review_request_id=request_id)[0]
        receipts = repo.find(
            'intake_receipts', source='grok-reviewer-webhook-wake',
            review_request_id=request_id)
    assert outbox['status'] == 'SENT'
    assert intake['status'] == 'READY'
    assert len(receipts) == 1
    assert receipts[0]['status'] == 'ACKED'
    assert receipts[0]['attempts'] == 1


def test_missing_wake_configuration_skips_worker_and_receipt(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / 'config' / 'grokbuddy.service.json').read_text(
        encoding='utf-8'))
    monkeypatch.delenv('GROKBUDDY_REVIEWER_WAKE_WEBHOOK_URL', raising=False)
    monkeypatch.delenv('GROKBUDDY_REVIEWER_WAKE_WEBHOOK_KEY', raising=False)
    args = grokbuddy_composite._parser().parse_args([
        '--runtime-dir', str(tmp_path / 'unused'),
    ])

    assert config['reviewerWakeWebhookUrlEnv'] == 'GROKBUDDY_REVIEWER_WAKE_WEBHOOK_URL'
    assert config['reviewerWakeWebhookKeyEnv'] == 'GROKBUDDY_REVIEWER_WAKE_WEBHOOK_KEY'
    assert grokbuddy_composite._reviewer_wake_transport(args) is None

    runtime, _, request_id, supervisor = _runtime_and_supervisor(tmp_path)
    result = supervisor.tick()
    assert 'reviewer_wake' not in result
    with runtime.db.transaction() as repo:
        assert repo.find(
            'intake_receipts', source='grok-reviewer-webhook-wake',
            review_request_id=request_id) == []


def test_windows_launcher_maps_optional_credentials_to_process_only():
    root = Path(__file__).resolve().parents[1]
    launcher = (root / 'scripts' / 'windows' / 'Start-GrokBuddyHub.ps1').read_text(
        encoding='utf-8-sig')
    credential_probe = (
        root / 'scripts' / 'windows' / 'Test-GrokBuddyCredentialStore.ps1'
    ).read_text(encoding='utf-8-sig')

    assert "'GrokBuddy/REVIEWER_WAKE_WEBHOOK_URL'" in launcher
    assert "'GrokBuddy/REVIEWER_WAKE_WEBHOOK_KEY'" in launcher
    assert "[Environment]::SetEnvironmentVariable($Name, $plain, 'Process')" in launcher
    assert '--reviewer-wake-webhook-url-env' in launcher
    assert '--reviewer-wake-webhook-key-env' in launcher
    assert "if ($reviewerWakeEnabled)" in launcher
    assert 'setx' not in launcher.lower()
    assert "'GrokBuddy/REVIEWER_WAKE_WEBHOOK_URL'" in credential_probe
    assert "'GrokBuddy/REVIEWER_WAKE_WEBHOOK_KEY'" in credential_probe


def test_incomplete_wake_configuration_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCAL_WAKE_URL', 'https://wake.example.invalid/hook')
    args = grokbuddy_composite._parser().parse_args([
        '--runtime-dir', str(tmp_path / 'unused'),
        '--reviewer-wake-webhook-url-env', 'LOCAL_WAKE_URL',
        '--reviewer-wake-webhook-key-env', 'LOCAL_WAKE_KEY',
    ])

    with pytest.raises(HubError):
        grokbuddy_composite._reviewer_wake_transport(args)


def test_wake_failure_never_rolls_back_sent_or_fails_task(tmp_path):
    wake = RecordingWakeTransport(SyntheticWakeError(retryable=False))
    runtime, task_id, request_id, supervisor = _runtime_and_supervisor(tmp_path, wake)

    result = supervisor.tick()

    assert result['dispatch'] == 'SENT'
    assert result['reviewer_wake'] == 'FAILED'
    assert runtime.hub.get_task(task_id)['state'] == 'PLAN_REVIEW_PENDING'
    assert runtime.hub.get_review(request_id)['request']['status'] == 'PENDING'
    with runtime.db.transaction() as repo:
        assert repo.find(
            'outbox_events', review_request_id=request_id)[0]['status'] == 'SENT'
        receipt = repo.find(
            'intake_receipts', source='grok-reviewer-webhook-wake',
            review_request_id=request_id)[0]
    assert receipt['status'] == 'FAILED'
    assert receipt['last_error_code'] == 'WAKE_TEST_FAILURE'


def test_wrong_reviewer_and_frozen_delivery_mismatch_do_not_send(tmp_path):
    wake = RecordingWakeTransport()
    runtime, _, request_id, supervisor = _runtime_and_supervisor(tmp_path, wake)
    with runtime.db.transaction() as repo:
        rr = repo.get('review_requests', request_id)
        rr['envelope']['expected_reviewer_actor_id'] = 'mock-reviewer'
        repo.save('review_requests', rr)
    assert supervisor.tick()['reviewer_wake'] is None
    assert wake.calls == []
    with runtime.db.transaction() as repo:
        rr = repo.get('review_requests', request_id)
        rr['envelope']['expected_reviewer_actor_id'] = B_ACTOR
        repo.save('review_requests', rr)
        outbox = repo.find('outbox_events', review_request_id=request_id)[0]
        outbox['delivery_key'] = 'wrong-delivery-key'
        repo.save('outbox_events', outbox)
    assert supervisor.tick()['reviewer_wake'] is None
    assert wake.calls == []


def test_http_transport_keeps_sender_key_out_of_body_and_uses_stable_idempotency():
    captured = {}

    class Response:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def getcode():
            return 200

        @staticmethod
        def read(_limit):
            return b'{"success":true}'

    def opener(request, timeout):
        captured['request'] = request
        captured['timeout'] = timeout
        return Response()

    transport = ReviewerWakeHttpTransport(
        'https://wake.example.invalid/routine?opaque=1',
        'local-sender-key-not-a-real-secret', opener=opener)
    assert transport.send('RR-local-1', 'a' * 64) == 200

    request = captured['request']
    body = json.loads(request.data.decode('utf-8'))
    assert body == {
        'event': 'reviewer_request_ready',
        'review_request_id': 'RR-local-1',
    }
    assert 'local-sender-key-not-a-real-secret' not in request.data.decode('utf-8')
    assert request.get_header('Authorization') == 'Bearer local-sender-key-not-a-real-secret'
    assert request.get_header('Idempotency-key') == 'a' * 64
    assert captured['timeout'] == 10
