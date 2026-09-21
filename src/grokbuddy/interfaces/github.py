"""Loopback-first GitHub Webhook surface for the authorized Phase 3 slice."""

from __future__ import annotations

import hashlib
import json

from grokbuddy.adapters.github import (GitHubAuthenticationError, GitHubWebhookError,
                                       parse_webhook_payload, validate_delivery_id,
                                       verify_webhook_signature)
from grokbuddy.domain.model import Conflict, HubError


MAX_WEBHOOK_BODY = 1024 * 1024


class GitHubWebhookApplication:
    def __init__(self, runtime, secret):
        self.runtime = runtime
        self.events = runtime.github_events
        self.secret = secret

    @staticmethod
    def _response(start_response, status, body):
        data = json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
        start_response(status, [("Content-Type", "application/json; charset=utf-8"),
                                ("Content-Length", str(len(data)))])
        return [data]

    def __call__(self, environ, start_response):
        if environ.get("PATH_INFO") != "/webhooks/github":
            return self._response(start_response, "404 Not Found", {
                "ok": False, "error": {"code": "NOT_FOUND", "message": "Unknown webhook route"}
            })
        if environ.get("REQUEST_METHOD") != "POST":
            return self._response(start_response, "405 Method Not Allowed", {
                "ok": False, "error": {"code": "METHOD_NOT_ALLOWED", "message": "POST is required"}
            })
        try:
            raw_length = environ.get("CONTENT_LENGTH", "")
            if not raw_length:
                raise GitHubWebhookError("Content-Length is required")
            length = int(raw_length)
            if length < 0 or length > MAX_WEBHOOK_BODY:
                return self._response(start_response, "413 Content Too Large", {
                    "ok": False, "error": {"code": "PAYLOAD_TOO_LARGE", "message": "Webhook body is too large"}
                })
            body = environ["wsgi.input"].read(length)
            if len(body) != length:
                raise GitHubWebhookError("Webhook body length does not match Content-Length")
        except (ValueError, TypeError, OSError, GitHubWebhookError) as exc:
            return self._response(start_response, "400 Bad Request", {
                "ok": False, "error": {"code": "VALIDATION_FAILURE", "message": str(exc)}
            })

        delivery_id = environ.get("HTTP_X_GITHUB_DELIVERY")
        event_name = environ.get("HTTP_X_GITHUB_EVENT")
        signature = environ.get("HTTP_X_HUB_SIGNATURE_256")
        raw_sha256 = hashlib.sha256(body).hexdigest()
        try:
            verify_webhook_signature(self.secret, body, signature)
            delivery_id = validate_delivery_id(delivery_id)
            event = parse_webhook_payload(event_name, body)
            receipt = self.events.ingest(delivery_id=delivery_id, event_name=event_name,
                                         raw_sha256=raw_sha256, event=event)
            status = "200 OK" if receipt["duplicate"] else "202 Accepted"
            return self._response(start_response, status, {"ok": True, "result": receipt})
        except GitHubAuthenticationError as exc:
            self.events.record_rejection(delivery_id=delivery_id, event_name=event_name,
                                         raw_sha256=raw_sha256, code=exc.code)
            return self._response(start_response, "401 Unauthorized", {
                "ok": False, "error": {"code": exc.code, "message": str(exc)}
            })
        except Conflict as exc:
            return self._response(start_response, "409 Conflict", {
                "ok": False, "error": {"code": exc.code, "message": str(exc)}
            })
        except HubError as exc:
            self.events.record_rejection(delivery_id=delivery_id, event_name=event_name,
                                         raw_sha256=raw_sha256, code=exc.code)
            return self._response(start_response, "422 Unprocessable Entity", {
                "ok": False, "error": {"code": exc.code, "message": str(exc)}
            })
