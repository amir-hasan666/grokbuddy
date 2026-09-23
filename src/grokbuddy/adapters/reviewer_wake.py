"""Best-effort HTTPS wake transport for the external Reviewer routine.

The wake request is only a notification.  The Reviewer must still fetch the
frozen request from the authenticated Reviewer HTTP API and post events there.
"""

import json
import re
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from grokbuddy.domain.model import HubError


_IDENTIFIER = re.compile(r"[A-Za-z0-9._:-]{1,200}\Z")
_MAX_RESPONSE_BYTES = 4096


class ReviewerWakeTransportError(Exception):
    """Secret-free transport failure classification for the wake worker."""

    def __init__(self, code, *, retryable, http_status_code=None):
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.http_status_code = http_status_code


class _NoRedirectHandler(HTTPRedirectHandler):
    """Do not forward the sender key to a redirect target."""

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


class ReviewerWakeHttpTransport:
    """Send one small, authenticated wake notification over HTTPS."""

    def __init__(self, webhook_url, sender_key, *, timeout=10, opener=None):
        if not isinstance(webhook_url, str) or any(c in webhook_url for c in "\r\n\t"):
            raise HubError("Reviewer wake webhook URL is invalid")
        parsed = urlsplit(webhook_url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.fragment):
            raise HubError("Reviewer wake webhook URL must be HTTPS without credentials or fragment")
        if (not isinstance(sender_key, str) or not sender_key
                or any(c in sender_key for c in "\r\n")):
            raise HubError("Reviewer wake sender key is invalid")
        if type(timeout) not in (int, float) or timeout <= 0 or timeout > 30:
            raise HubError("Reviewer wake timeout must be between 1 and 30 seconds")
        self._webhook_url = webhook_url
        self._sender_key = sender_key
        self._timeout = timeout
        self._opener = opener or build_opener(_NoRedirectHandler()).open

    @staticmethod
    def _validate_identifier(value, label):
        if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
            raise HubError(f"Reviewer wake {label} is invalid")

    @staticmethod
    def _http_failure(status):
        retryable = status in (408, 429) or status >= 500
        code = ("WAKE_CONSUMER_UNAVAILABLE" if status == 503 else
                "WAKE_HTTP_RETRYABLE" if retryable else
                "WAKE_HTTP_REJECTED" if status in (400, 401, 403, 405, 410, 422) else
                "WAKE_HTTP_UNCLASSIFIED")
        return ReviewerWakeTransportError(
            code, retryable=retryable, http_status_code=status)

    def send(self, request_id, deduplication_key):
        self._validate_identifier(request_id, "request ID")
        self._validate_identifier(deduplication_key, "deduplication key")
        payload = json.dumps(
            {
                "event": "reviewer_request_ready",
                "review_request_id": request_id,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request = Request(
            self._webhook_url,
            data=payload,
            method="POST",
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer " + self._sender_key,
                "Content-Type": "application/json",
                "Idempotency-Key": deduplication_key,
                "User-Agent": "grokbuddy-reviewer-wake/1",
            },
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                status = response.getcode()
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            raise self._http_failure(exc.code) from None
        except (TimeoutError, socket.timeout) as exc:
            raise ReviewerWakeTransportError(
                "WAKE_TIMEOUT", retryable=True) from exc
        except URLError as exc:
            raise ReviewerWakeTransportError(
                "WAKE_NETWORK_ERROR", retryable=True) from exc
        if not 200 <= status < 300:
            raise self._http_failure(status)
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise ReviewerWakeTransportError(
                "WAKE_RESPONSE_TOO_LARGE", retryable=False)
        return status
