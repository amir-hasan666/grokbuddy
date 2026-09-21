import hashlib
import hmac
import io
import json
import socket
import threading
from email.message import Message
from wsgiref.simple_server import make_server

import pytest

from grokbuddy.adapters.github import (FileGitHubCommentTransport,
                                        GitHubCommentTransportError,
                                        GitHubHttpCommentTransport)
from grokbuddy.interfaces.github import GitHubWebhookApplication


SECRET = "phase3-local-test-secret"
REPOSITORY_ID = 246810
REPOSITORY = "example/grokbuddy"
PULL_REQUEST = 17


class _HttpResponse:
    def __init__(self, status, value, headers=None):
        self.status = status
        self.value = value
        self.headers = Message()
        for key, item in (headers or {}).items():
            self.headers[key] = str(item)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def getcode(self):
        return self.status

    def read(self, _maximum=-1):
        return json.dumps(self.value).encode("utf-8")


class _SequenceOpener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _payload(*, event="pull_request", action="synchronize", revision="a" * 40):
    common = {
        "repository": {"id": REPOSITORY_ID, "full_name": REPOSITORY},
        "sender": {"id": 13579},
    }
    if event == "pull_request":
        return {
            **common,
            "action": action,
            "number": PULL_REQUEST,
            "pull_request": {"head": {"sha": revision}},
        }
    if event == "push":
        return {**common, "ref": "refs/heads/phase3", "after": revision}
    if event == "ping":
        return {**common, "zen": "Keep it logically awesome."}
    return {**common, "action": "created"}


def _bytes(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _signature(body):
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def _call(app, body, *, delivery="delivery-phase3-1", event="pull_request", signature=None):
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/webhooks/github",
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
        "HTTP_X_GITHUB_DELIVERY": delivery,
        "HTTP_X_GITHUB_EVENT": event,
    }
    if signature is not None:
        environ["HTTP_X_HUB_SIGNATURE_256"] = signature
    response = b"".join(app(environ, start_response))
    return captured["status"], json.loads(response)


def _prepare_final(flow):
    flow.executing()
    flow.package()
    assert flow.task["state"] == "SELF_TESTING"
    binding = flow.r.github_bindings.bind_pull_request(
        repository_id=REPOSITORY_ID,
        repository_full_name=REPOSITORY,
        pull_request_number=PULL_REQUEST,
        task_id=flow.id,
        hub_pointer_base="hub://phase3-test",
    )
    return binding


def test_loopback_webhook_http_endpoint_is_reachable(runtime):
    app = GitHubWebhookApplication(runtime, SECRET)
    body = _bytes(_payload(event="push", revision="d" * 40))
    server = make_server("127.0.0.1", 0, app)
    worker = threading.Thread(target=server.handle_request, daemon=True)
    worker.start()
    try:
        request = (
            "POST /webhooks/github HTTP/1.0\r\n"
            f"Host: 127.0.0.1:{server.server_port}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            "X-GitHub-Delivery: loopback-reachable\r\n"
            "X-GitHub-Event: push\r\n"
            f"X-Hub-Signature-256: {_signature(body)}\r\n"
            "\r\n"
        ).encode("ascii") + body
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(5)
        client.connect(("127.0.0.1", server.server_port))
        client.sendall(request)
        response = bytearray()
        while True:
            chunk = client.recv(8192)
            if not chunk:
                break
            response.extend(chunk)
        client.close()
    finally:
        worker.join(timeout=5)
        server.server_close()

    assert bytes(response).startswith(b"HTTP/1.0 202 Accepted")
    assert b'"status": "IGNORED"' in response


def test_signed_pull_request_synchronize_requests_final_review_and_stops_pending(flow):
    _prepare_final(flow)
    app = GitHubWebhookApplication(flow.r, SECRET)
    body = _bytes(_payload())

    status, response = _call(app, body, signature=_signature(body))

    assert status == "202 Accepted"
    result = response["result"]
    assert result["status"] == "APPLIED"
    assert result["effect"]["status"] == "PENDING"
    request_id = result["effect"]["review_request_id"]
    queried = flow.h.get_review(request_id)
    assert queried["request"]["status"] == "PENDING"
    assert queried["review"] is None
    assert flow.task["state"] == "FINAL_REVIEW_PENDING"
    assert not flow.rows("mock_jobs", id=request_id)
    assert len(flow.rows("review_requests", task_id=flow.id, review_type="FINAL_REVIEW")) == 1


@pytest.mark.parametrize("case", ["missing", "wrong", "tampered"])
def test_webhook_signature_missing_wrong_and_tampered_change_no_task_state(flow, case):
    _prepare_final(flow)
    app = GitHubWebhookApplication(flow.r, SECRET)
    original = _bytes(_payload())
    body = original
    signature = None
    if case == "wrong":
        signature = "sha256=" + "0" * 64
    elif case == "tampered":
        signature = _signature(original)
        body = original + b" "

    status, response = _call(app, body, delivery=f"signature-{case}", signature=signature)

    assert status == "401 Unauthorized"
    assert response["error"]["code"] == "AUTHENTICATION_FAILURE"
    assert flow.task["state"] == "SELF_TESTING"
    assert not flow.rows("github_events")
    rejected = [row for row in flow.h.audit_log(flow.id) if row["action"] == "GITHUB_WEBHOOK_REJECTED"]
    # Rejection Audit is global because an untrusted payload cannot select task_id.
    assert not rejected
    with flow.r.db.transaction() as repo:
        global_rejections = repo.find("audit_logs", task_id=None)
    assert any(row["action"] == "GITHUB_WEBHOOK_REJECTED" for row in global_rejections)


def test_same_delivery_and_same_semantic_event_are_idempotent(flow):
    _prepare_final(flow)
    app = GitHubWebhookApplication(flow.r, SECRET)
    body = _bytes(_payload())
    first_status, first = _call(app, body, delivery="delivery-idempotent", signature=_signature(body))
    second_status, second = _call(app, body, delivery="delivery-idempotent", signature=_signature(body))
    third_status, third = _call(app, body, delivery="delivery-new-header", signature=_signature(body))

    assert first_status == "202 Accepted"
    assert second_status == third_status == "200 OK"
    assert second["result"]["duplicate"] is True
    assert third["result"]["status"] == "DUPLICATE_SEMANTIC"
    request_ids = {
        first["result"]["effect"]["review_request_id"],
        second["result"]["effect"]["review_request_id"],
        third["result"]["effect"]["review_request_id"],
    }
    assert len(request_ids) == 1
    assert len(flow.rows("review_requests", task_id=flow.id, review_type="FINAL_REVIEW")) == 1


def test_delivery_id_reuse_with_different_valid_body_is_conflict(flow):
    app = GitHubWebhookApplication(flow.r, SECRET)
    first = _bytes(_payload(event="push", revision="b" * 40))
    changed = _bytes(_payload(event="push", revision="c" * 40))
    assert _call(app, first, delivery="delivery-conflict", event="push",
                 signature=_signature(first))[0] == "202 Accepted"

    status, response = _call(app, changed, delivery="delivery-conflict", event="push",
                             signature=_signature(changed))

    assert status == "409 Conflict"
    assert response["error"]["code"] == "CONFLICT"
    assert len(flow.rows("github_events")) == 1


@pytest.mark.parametrize(
    ("event", "action"),
    [("push", "push"), ("ping", "ping"), ("pull_request", "opened"),
     ("pull_request", "closed")],
)
def test_non_trigger_events_are_validated_recorded_and_ignored(flow, event, action):
    if event == "pull_request":
        _prepare_final(flow)
    app = GitHubWebhookApplication(flow.r, SECRET)
    body = _bytes(_payload(event=event, action=action))

    status, response = _call(app, body, delivery=f"ignored-{event}-{action}", event=event,
                             signature=_signature(body))

    assert status == "202 Accepted"
    assert response["result"]["status"] == "IGNORED"
    assert not flow.rows("review_requests", task_id=flow.id, review_type="FINAL_REVIEW")


@pytest.mark.parametrize("event", ["issue_comment", "pull_request_review_comment"])
def test_comment_events_are_not_listened_to(flow, event):
    app = GitHubWebhookApplication(flow.r, SECRET)
    body = _bytes(_payload(event=event))

    status, response = _call(app, body, delivery="disallowed-" + event, event=event,
                             signature=_signature(body))

    assert status == "422 Unprocessable Entity"
    assert response["error"]["code"] == "VALIDATION_FAILURE"
    assert not flow.rows("github_events")


def test_completed_final_review_updates_existing_marker_comment(flow, tmp_path):
    binding = _prepare_final(flow)
    app = GitHubWebhookApplication(flow.r, SECRET)
    body = _bytes(_payload())
    _, webhook = _call(app, body, delivery="projection-source", signature=_signature(body))
    request_id = webhook["result"]["effect"]["review_request_id"]
    flow.r.mock.configure(request_id, "PASS")
    assert flow.r.tick()["event"] == "APPLIED"
    completed = flow.h.get_review(request_id)
    review_id = completed["review"]["id"]

    comments_path = tmp_path / "local-github-comments.json"
    transport = FileGitHubCommentTransport(comments_path)
    stale = transport.create_comment(
        binding, f"<!-- grokbuddy-final-review:{review_id} -->\nstale projection")
    projection = flow.r.github_projections.enqueue_final_review(request_id)

    assert flow.r.github_projections.project_one(transport) == "UPDATED"
    value = json.loads(comments_path.read_text(encoding="utf-8"))
    assert len(value["comments"]) == 1
    comment = value["comments"][0]
    assert comment["id"] == stale["id"]
    assert f"<!-- grokbuddy-final-review:{review_id} -->" in comment["body"]
    assert "status=COMPLETED" in comment["body"]
    assert "verdict=PASS" in comment["body"]
    assert f"task_id={flow.id}" in comment["body"]
    assert f"review_id={review_id}" in comment["body"]
    assert "hub_pointer=hub://phase3-test/tasks/" in comment["body"]
    assert flow.rows("github_comment_projections", id=projection["id"])[0]["status"] == "SENT"

    # Re-enqueueing an immutable Review does not create or update another comment.
    assert flow.r.github_projections.enqueue_final_review(request_id)["status"] == "SENT"
    assert flow.r.github_projections.project_one(transport) is None
    assert len(json.loads(comments_path.read_text(encoding="utf-8"))["comments"]) == 1


def test_github_http_comment_transport_finds_creates_and_updates_by_marker():
    marker = "<!-- grokbuddy-final-review:REV-test -->"
    binding = {"repository_full_name": "example/grokbuddy", "pull_request_number": 17}
    opener = _SequenceOpener(
        _HttpResponse(200, [{"id": 41, "body": marker + "\nold", "html_url": "https://example/41"}]),
        _HttpResponse(200, {"id": 41, "body": marker + "\nnew", "html_url": "https://example/41"}),
        _HttpResponse(200, []),
        _HttpResponse(201, {"id": 42, "body": marker, "html_url": "https://example/42"}),
    )
    transport = GitHubHttpCommentTransport("fake-test-token", opener=opener)

    assert transport.find_comment(binding, marker)["id"] == "41"
    assert transport.update_comment(binding, "41", marker + "\nnew")["id"] == "41"
    assert transport.find_comment(binding, marker) is None
    assert transport.create_comment(binding, marker)["id"] == "42"

    methods = [request.get_method() for request, _ in opener.requests]
    assert methods == ["GET", "PATCH", "GET", "POST"]
    assert all(request.get_header("Authorization") == "Bearer fake-test-token"
               for request, _ in opener.requests)
    assert opener.requests[0][0].full_url.endswith(
        "/repos/example/grokbuddy/issues/17/comments?per_page=100&page=1")
    assert opener.requests[1][0].full_url.endswith(
        "/repos/example/grokbuddy/issues/comments/41")


@pytest.mark.parametrize(
    ("status", "headers", "message", "code", "retryable"),
    [
        (401, {}, "Bad credentials", "AUTH_FAILED", False),
        (403, {}, "Resource not accessible by personal access token",
         "PERMISSION_DENIED", False),
        (403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1789600123"},
         "API rate limit exceeded", "RATE_LIMITED", True),
        (403, {"Retry-After": "60"}, "You have exceeded a secondary limit",
         "RATE_LIMITED", True),
        (429, {"Retry-After": "61"}, "secondary rate limit", "RATE_LIMITED", True),
        (500, {}, "server error", "SERVICE_UNAVAILABLE", True),
    ],
)
def test_github_http_comment_transport_classifies_safe_failures(
        status, headers, message, code, retryable):
    header_message = Message()
    for key, value in headers.items():
        header_message[key] = value
    error = GitHubHttpCommentTransport._http_failure(
        status, header_message, json.dumps({"message": message}).encode())

    assert error.code == code
    assert error.retryable is retryable
    assert error.http_status == status
    assert "Authorization" not in json.dumps(error.safe_metadata)


def test_github_http_comment_transport_classifies_timeout_without_token_leak():
    opener = _SequenceOpener(TimeoutError("request timed out with fake-test-token"))
    transport = GitHubHttpCommentTransport("fake-test-token", opener=opener)

    with pytest.raises(GitHubCommentTransportError) as captured:
        transport.find_comment(
            {"repository_full_name": "example/grokbuddy", "pull_request_number": 17},
            "<!-- marker -->")

    assert captured.value.code == "TIMEOUT"
    assert captured.value.retryable is True
    assert "fake-test-token" not in str(captured.value)


def _completed_projection(flow):
    _prepare_final(flow)
    app = GitHubWebhookApplication(flow.r, SECRET)
    body = _bytes(_payload())
    _, webhook = _call(app, body, delivery="http-projection-source", signature=_signature(body))
    request_id = webhook["result"]["effect"]["review_request_id"]
    flow.r.mock.configure(request_id, "PASS")
    assert flow.r.tick()["event"] == "APPLIED"
    return flow.r.github_projections.enqueue_final_review(request_id)


def test_non_retryable_auth_failure_immediately_fails_projection(flow):
    projection = _completed_projection(flow)

    class Unauthorized:
        def find_comment(self, _binding, _marker):
            raise GitHubCommentTransportError(
                "AUTH_FAILED", "GitHub authentication failed", retryable=False,
                http_status=401, safe_metadata={"github_request_id": "SAFE-REQUEST-1"})

    assert flow.r.github_projections.project_one(Unauthorized()) == "FAILED"
    row = flow.rows("github_comment_projections", id=projection["id"])[0]
    assert row["status"] == "FAILED"
    assert row["attempts"] == 1
    assert row["last_safe_error"] == "AUTH_FAILED"
    assert row["last_http_status"] == 401
    assert row["last_error_retryable"] is False
    assert row["last_error_metadata"] == {"github_request_id": "SAFE-REQUEST-1"}


def test_rate_limit_retries_are_bounded_and_preserve_safe_metadata(flow):
    projection = _completed_projection(flow)

    class RateLimited:
        def __init__(self):
            self.find_calls = 0

        def find_comment(self, _binding, _marker):
            self.find_calls += 1
            raise GitHubCommentTransportError(
                "RATE_LIMITED", "GitHub API rate limit was reached", retryable=True,
                http_status=403,
                safe_metadata={"retry_after_seconds": 1, "rate_limit_remaining": 0})

    transport = RateLimited()
    for attempt in range(1, flow.r.settings.delivery_max_attempts + 1):
        expected = "FAILED" if attempt == flow.r.settings.delivery_max_attempts else "RETRY"
        assert flow.r.github_projections.project_one(transport) == expected
        row = flow.rows("github_comment_projections", id=projection["id"])[0]
        assert row["attempts"] == attempt
        assert row["status"] == expected
        assert row["last_http_status"] == 403
        assert row["last_safe_error"] == "RATE_LIMITED"
        assert row["last_error_metadata"]["rate_limit_remaining"] == 0
        flow.r.clock.advance(1)
    assert transport.find_calls == flow.r.settings.delivery_max_attempts


def test_timeout_after_remote_create_recovers_by_marker_without_duplicate(flow):
    projection = _completed_projection(flow)

    class AmbiguousCreate:
        def __init__(self):
            self.comments = []
            self.find_calls = 0
            self.create_calls = 0

        def find_comment(self, _binding, marker):
            self.find_calls += 1
            return next((dict(item) for item in self.comments if marker in item["body"]), None)

        def create_comment(self, _binding, body):
            self.create_calls += 1
            self.comments.append({"id": "91", "body": body, "url": "https://example/91"})
            raise GitHubCommentTransportError(
                "TIMEOUT", "GitHub API request timed out", retryable=True)

        def update_comment(self, *_args):
            raise AssertionError("unchanged marker comment must not be updated")

    transport = AmbiguousCreate()
    assert flow.r.github_projections.project_one(transport) == "UNKNOWN"
    flow.r.clock.advance(2)
    assert flow.r.github_projections.project_one(transport) == "UNCHANGED"
    row = flow.rows("github_comment_projections", id=projection["id"])[0]
    assert row["status"] == "SENT"
    assert row["comment_id"] == "91"
    assert transport.find_calls == 2
    assert transport.create_calls == 1
    assert len(transport.comments) == 1
