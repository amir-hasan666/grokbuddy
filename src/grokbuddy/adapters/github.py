"""GitHub boundary helpers used by the Phase 3/3.5 webhook and projection.

The module performs transport authentication and parses only the small event
surface authorized for Phase 3.  It contains no Task state rules.  The file
transport remains the offline default; the HTTPS transport is explicit opt-in.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

from grokbuddy.domain.model import HubError


DISALLOWED_EVENTS = {"issue_comment", "pull_request_review_comment"}
SUPPORTED_EVENTS = {"ping", "push", "pull_request"}
_DELIVERY = re.compile(r"[A-Za-z0-9._:-]{1,200}\Z")
_SHA = re.compile(r"[0-9a-fA-F]{7,64}\Z")
_FULL_NAME = re.compile(r"[^/\s]+/[^/\s]+\Z")
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,200}\Z")
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class GitHubAuthenticationError(HubError):
    code = "AUTHENTICATION_FAILURE"


class GitHubWebhookError(HubError):
    code = "VALIDATION_FAILURE"


class GitHubCommentTransportError(HubError):
    """Classified GitHub REST failure with only bounded, non-secret metadata."""

    def __init__(self, code, message, *, retryable, http_status=None, safe_metadata=None):
        super().__init__(message)
        self.code = code
        self.retryable = bool(retryable)
        self.http_status = http_status if type(http_status) is int else None
        self.safe_metadata = dict(safe_metadata or {})


def validate_delivery_id(value: str | None) -> str:
    if not isinstance(value, str) or not _DELIVERY.fullmatch(value):
        raise GitHubWebhookError("X-GitHub-Delivery is missing or invalid")
    return value


def verify_webhook_signature(secret: str | bytes, body: bytes, signature: str | None) -> None:
    """Verify GitHub's sha256 HMAC over the exact request bytes."""
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    if not isinstance(secret, bytes) or not secret:
        raise GitHubAuthenticationError("Webhook secret is not configured")
    if not isinstance(body, bytes):
        raise GitHubWebhookError("Webhook body must be bytes")
    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    if not isinstance(signature, str) or not hmac.compare_digest(expected, signature):
        raise GitHubAuthenticationError("Webhook signature is missing or invalid")


def _object(value, name):
    if not isinstance(value, dict):
        raise GitHubWebhookError(f"{name} must be an object")
    return value


def _positive_integer(value, name):
    if type(value) is not int or value < 1:
        raise GitHubWebhookError(f"{name} must be a positive integer")
    return value


def parse_webhook_payload(event_name: str | None, body: bytes) -> dict:
    """Return bounded metadata; raw payload content is never put in Audit."""
    if event_name in DISALLOWED_EVENTS:
        raise GitHubWebhookError(f"GitHub event {event_name} is not subscribed")
    if event_name not in SUPPORTED_EVENTS:
        raise GitHubWebhookError("Unsupported GitHub event")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeError, ValueError, TypeError) as exc:
        raise GitHubWebhookError("Webhook body must be a UTF-8 JSON object") from exc
    payload = _object(payload, "payload")
    repository = _object(payload.get("repository"), "repository")
    repository_id = _positive_integer(repository.get("id"), "repository.id")
    full_name = repository.get("full_name")
    if not isinstance(full_name, str) or len(full_name) > 200 or not _FULL_NAME.fullmatch(full_name):
        raise GitHubWebhookError("repository.full_name is invalid")
    sender = payload.get("sender")
    sender_id = None
    if sender is not None:
        sender_id = _positive_integer(_object(sender, "sender").get("id"), "sender.id")

    base = {
        "event_name": event_name,
        "repository_id": repository_id,
        "repository_full_name": full_name,
        "sender_id": sender_id,
    }
    if event_name == "ping":
        return {
            **base,
            "action": "ping",
            "resource_type": "repository",
            "resource_id": str(repository_id),
            "resource_revision": hashlib.sha256(body).hexdigest(),
            "canonical_key": f"github:{repository_id}:ping:{hashlib.sha256(body).hexdigest()}",
            "advances_final_review": False,
        }
    if event_name == "push":
        ref, after = payload.get("ref"), payload.get("after")
        if not isinstance(ref, str) or not ref or len(ref) > 300:
            raise GitHubWebhookError("push ref is invalid")
        if not isinstance(after, str) or not _SHA.fullmatch(after):
            raise GitHubWebhookError("push after SHA is invalid")
        return {
            **base,
            "action": "push",
            "resource_type": "ref",
            "resource_id": ref,
            "resource_revision": after.lower(),
            "canonical_key": f"github:{repository_id}:push:{ref}:{after.lower()}",
            "advances_final_review": False,
        }

    action = payload.get("action")
    if not isinstance(action, str) or not action or len(action) > 80:
        raise GitHubWebhookError("pull_request action is invalid")
    number = _positive_integer(payload.get("number"), "pull_request number")
    pull_request = _object(payload.get("pull_request"), "pull_request")
    head = _object(pull_request.get("head"), "pull_request.head")
    head_sha = head.get("sha")
    if not isinstance(head_sha, str) or not _SHA.fullmatch(head_sha):
        raise GitHubWebhookError("pull_request head SHA is invalid")
    revision = head_sha.lower()
    return {
        **base,
        "action": action,
        "resource_type": "pull_request",
        "resource_id": str(number),
        "pull_request_number": number,
        "resource_revision": revision,
        "canonical_key": f"github:{repository_id}:pull_request:{number}:{action}:{revision}",
        "advances_final_review": action == "synchronize",
    }


class FileGitHubCommentTransport:
    """A durable local Comment test double for Phase 3 acceptance.

    It intentionally has no HTTP/token support.  Production GitHub deployment
    remains outside the current authorization.
    """

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self):
        if not self.path.exists():
            return {"next_id": 1, "comments": []}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise HubError("Local GitHub Comment store is invalid") from exc
        if not isinstance(value, dict) or type(value.get("next_id")) is not int or not isinstance(value.get("comments"), list):
            raise HubError("Local GitHub Comment store is invalid")
        return value

    def _save(self, value):
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)

    @staticmethod
    def _scope(binding, comment):
        return (comment.get("repository_full_name"), comment.get("pull_request_number")) == (
            binding["repository_full_name"], binding["pull_request_number"])

    def find_comment(self, binding: dict, marker: str) -> dict | None:
        for comment in self._load()["comments"]:
            if self._scope(binding, comment) and marker in comment.get("body", ""):
                return dict(comment)
        return None

    def create_comment(self, binding: dict, body: str) -> dict:
        value = self._load()
        identity = str(value["next_id"])
        value["next_id"] += 1
        comment = {
            "id": identity,
            "repository_full_name": binding["repository_full_name"],
            "pull_request_number": binding["pull_request_number"],
            "body": body,
            "url": f"mock-github://{binding['repository_full_name']}/pull/{binding['pull_request_number']}#comment-{identity}",
        }
        value["comments"].append(comment)
        self._save(value)
        return dict(comment)

    def update_comment(self, binding: dict, comment_id: str, body: str) -> dict:
        value = self._load()
        for comment in value["comments"]:
            if str(comment.get("id")) == str(comment_id) and self._scope(binding, comment):
                comment["body"] = body
                self._save(value)
                return dict(comment)
        raise HubError("Existing projected GitHub Comment was not found")


class GitHubHttpCommentTransport:
    """Explicit opt-in GitHub REST transport for ordinary PR issue comments only."""

    def __init__(self, token, *, api_base_url="https://api.github.com", timeout=15,
                 max_comment_pages=10, opener=None):
        if not isinstance(token, str) or not token or "\r" in token or "\n" in token:
            raise HubError("GitHub token is required")
        parsed = urlsplit(api_base_url)
        if (parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password
                or parsed.query or parsed.fragment):
            raise HubError("GitHub API base URL must be an HTTPS origin or base path")
        if type(timeout) not in (int, float) or timeout <= 0 or timeout > 120:
            raise HubError("GitHub HTTP timeout must be between 1 and 120 seconds")
        if type(max_comment_pages) is not int or not 1 <= max_comment_pages <= 100:
            raise HubError("GitHub Comment pagination limit must be between 1 and 100")
        self._token = token
        self.api_base_url = api_base_url.rstrip("/")
        self.timeout = timeout
        self.max_comment_pages = max_comment_pages
        self._opener = opener or urlopen

    @staticmethod
    def _binding_path(binding):
        full_name = binding.get("repository_full_name")
        number = binding.get("pull_request_number")
        if not isinstance(full_name, str) or not _FULL_NAME.fullmatch(full_name):
            raise HubError("GitHub binding repository_full_name is invalid")
        if type(number) is not int or number < 1:
            raise HubError("GitHub binding pull_request_number is invalid")
        owner, repository = full_name.split("/", 1)
        return quote(owner, safe=""), quote(repository, safe=""), number

    @staticmethod
    def _safe_error_metadata(headers):
        headers = headers or {}
        metadata = {}
        retry_after = headers.get("Retry-After")
        if isinstance(retry_after, str) and retry_after.isdigit():
            metadata["retry_after_seconds"] = min(int(retry_after), 86400)
        reset = headers.get("X-RateLimit-Reset")
        if isinstance(reset, str) and reset.isdigit():
            metadata["rate_limit_reset"] = min(int(reset), 4102444800)
        remaining = headers.get("X-RateLimit-Remaining")
        if isinstance(remaining, str) and remaining.isdigit():
            metadata["rate_limit_remaining"] = min(int(remaining), 1_000_000)
        resource = headers.get("X-RateLimit-Resource")
        if isinstance(resource, str) and re.fullmatch(r"[A-Za-z0-9._:-]{1,80}", resource):
            metadata["rate_limit_resource"] = resource
        request_id = headers.get("X-GitHub-Request-Id")
        if isinstance(request_id, str) and _SAFE_REQUEST_ID.fullmatch(request_id):
            metadata["github_request_id"] = request_id
        return metadata

    @staticmethod
    def _message(raw):
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, ValueError, TypeError):
            return ""
        message = value.get("message") if isinstance(value, dict) else None
        return message if isinstance(message, str) else ""

    @classmethod
    def _http_failure(cls, status, headers, raw):
        metadata = cls._safe_error_metadata(headers)
        message = cls._message(raw).lower()
        rate_limited = (
            status == 429
            or "retry_after_seconds" in metadata
            or metadata.get("rate_limit_remaining") == 0
            or "rate limit" in message
            or "secondary rate" in message
            or "abuse detection" in message
        )
        if status == 401:
            return GitHubCommentTransportError(
                "AUTH_FAILED", "GitHub authentication failed", retryable=False,
                http_status=status, safe_metadata=metadata)
        if status == 403 and not rate_limited:
            return GitHubCommentTransportError(
                "PERMISSION_DENIED", "GitHub Comment permission was denied", retryable=False,
                http_status=status, safe_metadata=metadata)
        if rate_limited:
            return GitHubCommentTransportError(
                "RATE_LIMITED", "GitHub API rate limit was reached", retryable=True,
                http_status=status, safe_metadata=metadata)
        if status == 408:
            return GitHubCommentTransportError(
                "TIMEOUT", "GitHub API request timed out", retryable=True,
                http_status=status, safe_metadata=metadata)
        if status >= 500:
            return GitHubCommentTransportError(
                "SERVICE_UNAVAILABLE", "GitHub API service failure", retryable=True,
                http_status=status, safe_metadata=metadata)
        code = "NOT_FOUND" if status == 404 else "HTTP_CLIENT_ERROR"
        return GitHubCommentTransportError(
            code, "GitHub API rejected the Comment request", retryable=False,
            http_status=status, safe_metadata=metadata)

    @staticmethod
    def _read_bounded(response):
        raw = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise GitHubCommentTransportError(
                "RESPONSE_TOO_LARGE", "GitHub API response exceeded the safety limit",
                retryable=False)
        return raw

    def _request(self, method, path, *, payload=None, expected_status):
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = Request(
            self.api_base_url + path,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": "Bearer " + self._token,
                "Content-Type": "application/json",
                "User-Agent": "grokbuddy-phase35",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with self._opener(request, timeout=self.timeout) as response:
                status = response.getcode()
                raw = self._read_bounded(response)
                headers = response.headers
        except HTTPError as exc:
            raw = exc.read(_MAX_RESPONSE_BYTES + 1)
            raise self._http_failure(exc.code, exc.headers, raw[:_MAX_RESPONSE_BYTES]) from None
        except (TimeoutError, socket.timeout) as exc:
            raise GitHubCommentTransportError(
                "TIMEOUT", "GitHub API request timed out", retryable=True) from exc
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise GitHubCommentTransportError(
                    "TIMEOUT", "GitHub API request timed out", retryable=True) from exc
            raise GitHubCommentTransportError(
                "NETWORK_ERROR", "GitHub API network request failed", retryable=True) from exc
        if status != expected_status:
            raise self._http_failure(status, headers, raw)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, ValueError, TypeError) as exc:
            raise GitHubCommentTransportError(
                "INVALID_RESPONSE", "GitHub API returned invalid JSON", retryable=False,
                http_status=status, safe_metadata=self._safe_error_metadata(headers)) from exc
        return value

    @staticmethod
    def _comment_receipt(value):
        if not isinstance(value, dict) or type(value.get("id")) is not int:
            raise GitHubCommentTransportError(
                "INVALID_RESPONSE", "GitHub API returned an invalid Comment receipt",
                retryable=False)
        body = value.get("body")
        if not isinstance(body, str):
            raise GitHubCommentTransportError(
                "INVALID_RESPONSE", "GitHub API returned an invalid Comment body",
                retryable=False)
        url = value.get("html_url") or value.get("url")
        return {"id": str(value["id"]), "body": body, "url": url}

    def find_comment(self, binding: dict, marker: str) -> dict | None:
        owner, repository, number = self._binding_path(binding)
        if not isinstance(marker, str) or not marker:
            raise HubError("GitHub Comment marker is required")
        base = f"/repos/{owner}/{repository}/issues/{number}/comments"
        for page in range(1, self.max_comment_pages + 1):
            query = urlencode({"per_page": 100, "page": page})
            values = self._request("GET", base + "?" + query, expected_status=200)
            if not isinstance(values, list):
                raise GitHubCommentTransportError(
                    "INVALID_RESPONSE", "GitHub API returned an invalid Comment list",
                    retryable=False)
            for value in values:
                if isinstance(value, dict) and marker in str(value.get("body") or ""):
                    return self._comment_receipt(value)
            if len(values) < 100:
                return None
        raise GitHubCommentTransportError(
            "PAGINATION_LIMIT", "GitHub Comment search reached the configured page limit",
            retryable=False)

    def create_comment(self, binding: dict, body: str) -> dict:
        owner, repository, number = self._binding_path(binding)
        value = self._request(
            "POST", f"/repos/{owner}/{repository}/issues/{number}/comments",
            payload={"body": body}, expected_status=201)
        return self._comment_receipt(value)

    def update_comment(self, binding: dict, comment_id: str, body: str) -> dict:
        owner, repository, _ = self._binding_path(binding)
        if not isinstance(comment_id, str) or not comment_id.isdigit():
            raise HubError("GitHub Comment id is invalid")
        value = self._request(
            "PATCH", f"/repos/{owner}/{repository}/issues/comments/{comment_id}",
            payload={"body": body}, expected_status=200)
        return self._comment_receipt(value)
