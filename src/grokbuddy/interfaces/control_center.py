"""Authenticated read-only Human website and JSON endpoints."""

from __future__ import annotations

import base64
import json
import re
import secrets
from pathlib import Path
from urllib.parse import parse_qs

import anyio

from .control_center_query import ControlCenterQuery
from grokbuddy.domain.model import HubError, NotFound, PermissionDenied


_DETAIL = re.compile(r"^/control/api/tasks/(TASK-[A-Za-z0-9-]+)$")
_TIMELINE = re.compile(r"^/control/api/tasks/(TASK-[A-Za-z0-9-]+)/events$")
_ARTIFACT = re.compile(
    r"^/control/api/tasks/(TASK-[A-Za-z0-9-]+)/artifacts/(ART-[A-Za-z0-9-]+)(/preview)?$"
)
_STATIC = Path(__file__).with_name("control_center_static")
_SECURITY_HEADERS = (
    (b"cache-control", b"no-store"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
    (b"content-security-policy",
     b"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
     b"base-uri 'none'; form-action 'none'; frame-ancestors 'none'"),
)


async def _send(send, status, content, mime, *, head=False, headers=()):
    response_headers = [
        (b"content-type", mime.encode("ascii")),
        (b"content-length", str(len(content)).encode("ascii")),
        *_SECURITY_HEADERS, *headers,
    ]
    await send({"type": "http.response.start", "status": status, "headers": response_headers})
    await send({"type": "http.response.body", "body": b"" if head else content})


async def _json(send, status, value, *, head=False, headers=()):
    content = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    await _send(send, status, content, "application/json; charset=utf-8",
                head=head, headers=headers)


class ControlCenterApplication:
    def __init__(self, runtime, token, *, reviewer_actor_id="grok-reviewer-b"):
        if not isinstance(token, str) or len(token.encode("utf-8")) < 32:
            raise HubError("Control Center requires a dedicated token of at least 32 UTF-8 bytes")
        self.expected = b"Basic " + base64.b64encode(b"human:" + token.encode("utf-8"))
        self.query = ControlCenterQuery(runtime, reviewer_actor_id)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await _json(send, 404, {"error": "not_found"})
            return
        auth = [value for name, value in scope.get("headers", [])
                if name.lower() == b"authorization"]
        if len(auth) != 1 or not secrets.compare_digest(auth[0], self.expected):
            await _json(send, 401, {"error": "unauthorized"}, headers=(
                (b"www-authenticate", b'Basic realm="GrokBuddy Control Center", charset="UTF-8"'),))
            return
        method = scope.get("method")
        if method not in ("GET", "HEAD"):
            await _json(send, 405, {"error": "method_not_allowed"},
                        headers=((b"allow", b"GET, HEAD"),))
            return
        head = method == "HEAD"
        path = scope.get("path", "")
        try:
            if path in ("/control", "/control/"):
                await _send(send, 200, (_STATIC / "index.html").read_bytes(),
                            "text/html; charset=utf-8", head=head)
                return
            if path == "/control/app.js":
                await _send(send, 200, (_STATIC / "app.js").read_bytes(),
                            "text/javascript; charset=utf-8", head=head)
                return
            if path == "/control/style.css":
                await _send(send, 200, (_STATIC / "style.css").read_bytes(),
                            "text/css; charset=utf-8", head=head)
                return
            if path == "/control/api/tasks":
                value = await anyio.to_thread.run_sync(self.query.list_tasks)
                await _json(send, 200, {"tasks": value}, head=head)
                return
            match = _DETAIL.fullmatch(path)
            if match:
                value = await anyio.to_thread.run_sync(self.query.task_detail, match[1])
                await _json(send, 200, value, head=head)
                return
            match = _TIMELINE.fullmatch(path)
            if match:
                try:
                    params = parse_qs(scope.get("query_string", b"").decode("ascii"),
                                      keep_blank_values=True)
                except UnicodeError as exc:
                    raise HubError("Invalid timeline cursor") from exc
                if set(params) - {"cursor"} or len(params.get("cursor", [])) > 1:
                    raise HubError("Invalid timeline cursor")
                cursor = params.get("cursor", [None])[0]
                value = await anyio.to_thread.run_sync(
                    lambda: self.query.timeline(match[1], cursor))
                await _json(send, 200, value, head=head)
                return
            match = _ARTIFACT.fullmatch(path)
            if match:
                preview = bool(match[3])
                meta, content = await anyio.to_thread.run_sync(
                    lambda: self.query.artifact_bytes(match[1], match[2], preview=preview))
                if preview:
                    await _json(send, 200, {"artifact": meta, "text": content}, head=head)
                    return
                await _send(send, 200, content, "application/octet-stream", head=head,
                            headers=(
                                (b"content-disposition",
                                 f'attachment; filename="{meta["id"]}.bin"'.encode("ascii")),
                                (b"x-content-sha256", meta["sha256"].encode("ascii")),
                            ))
                return
            await _json(send, 404, {"error": "not_found"}, head=head)
        except NotFound:
            await _json(send, 404, {"error": "not_found"}, head=head)
        except PermissionDenied:
            await _json(send, 403, {"error": "forbidden"}, head=head)
        except HubError:
            await _json(send, 422, {"error": "invalid_request"}, head=head)
