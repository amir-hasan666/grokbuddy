"""ASGI composition root for webhook, health, and read-only Remote MCP."""

from __future__ import annotations

import json
import io
import secrets
import sys

import anyio

from mcp.server.transport_security import TransportSecuritySettings

from grokbuddy.domain.model import HubError
from .github import GitHubWebhookApplication, MAX_WEBHOOK_BODY
from .remote_mcp import create_remote_mcp_server


LOCAL_ALLOWED_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
LOCAL_ALLOWED_ORIGINS = [
    "http://127.0.0.1:*",
    "http://localhost:*",
    "http://[::1]:*",
]


async def _json_response(send, status, body, *, extra_headers=()):
    data = json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
    headers = [
        (b"content-type", b"application/json; charset=utf-8"),
        (b"content-length", str(len(data)).encode("ascii")),
        *extra_headers,
    ]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": data})


class BearerTokenBoundary:
    """Fail-closed pre-shared token boundary in front of the MCP transport."""

    def __init__(self, app, token):
        if not isinstance(token, str) or not token:
            raise HubError("GROKBUDDY_MCP_TOKEN must be set and non-empty")
        self.app = app
        self.expected = ("Bearer " + token).encode("utf-8")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        authorization = [
            value for name, value in scope.get("headers", [])
            if name.lower() == b"authorization"
        ]
        authorized = len(authorization) == 1 and secrets.compare_digest(
            authorization[0], self.expected
        )
        if not authorized:
            await _json_response(
                send,
                401,
                {"error": "unauthorized"},
                extra_headers=((b"www-authenticate", b"Bearer"),),
            )
            return
        if scope.get("method") != "POST":
            await _json_response(
                send,
                405,
                {"error": "method_not_allowed"},
                extra_headers=((b"allow", b"POST"),),
            )
            return
        await self.app(scope, receive, send)


class OriginalWebhookASGIBridge:
    """Adapt the existing synchronous webhook application without changing it."""

    def __init__(self, app):
        self.app = app

    @staticmethod
    def _invoke(app, scope, body):
        server = scope.get("server") or ("localhost", 80)
        environ = {
            "REQUEST_METHOD": scope["method"],
            "SCRIPT_NAME": "",
            "PATH_INFO": scope["path"],
            "QUERY_STRING": scope.get("query_string", b"").decode("ascii"),
            "SERVER_PROTOCOL": f"HTTP/{scope.get('http_version', '1.1')}",
            "SERVER_NAME": server[0],
            "SERVER_PORT": str(server[1]),
            "wsgi.version": (1, 0),
            "wsgi.url_scheme": scope.get("scheme", "http"),
            "wsgi.input": io.BytesIO(body),
            "wsgi.errors": sys.stderr,
            "wsgi.multithread": True,
            "wsgi.multiprocess": False,
            "wsgi.run_once": False,
        }
        for raw_name, raw_value in scope.get("headers", []):
            name = raw_name.decode("latin1")
            if name == "content-length":
                key = "CONTENT_LENGTH"
            elif name == "content-type":
                key = "CONTENT_TYPE"
            else:
                key = "HTTP_" + name.upper().replace("-", "_")
            value = raw_value.decode("latin1")
            environ[key] = environ[key] + "," + value if key in environ else value
        captured = {}

        def start_response(status, headers, exc_info=None):
            if exc_info is not None:
                raise exc_info[1].with_traceback(exc_info[2])
            captured["status"] = int(status.split(" ", 1)[0])
            captured["headers"] = [
                (name.encode("ascii").lower(), value.encode("ascii"))
                for name, value in headers
            ]

        response = app(environ, start_response)
        try:
            response_body = b"".join(response)
        finally:
            close = getattr(response, "close", None)
            if close is not None:
                close()
        return captured["status"], captured["headers"], response_body

    async def __call__(self, scope, receive, send):
        body = bytearray()
        lengths = [
            value for name, value in scope.get("headers", [])
            if name.lower() == b"content-length"
        ]
        try:
            expected_length = int(lengths[0]) if len(lengths) == 1 else -1
        except ValueError:
            expected_length = -1
        if scope.get("method") == "POST" and 0 <= expected_length <= MAX_WEBHOOK_BODY:
            more_body = True
            while more_body and len(body) < expected_length:
                message = await receive()
                remaining = expected_length - len(body)
                body.extend(message.get("body", b"")[:remaining])
                more_body = message.get("more_body", False)
        status, headers, response_body = await anyio.to_thread.run_sync(
            self._invoke, self.app, scope, bytes(body)
        )
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": response_body})


class CompositeApplication:
    """Route exact Phase 4 paths while preserving the original webhook WSGI app."""

    def __init__(self, webhook_app, mcp_app, mcp_token, grok_reviewer_app=None,
                 readiness_check=None):
        self.webhook_app = OriginalWebhookASGIBridge(webhook_app)
        self.mcp_app = mcp_app
        self.authenticated_mcp_app = BearerTokenBoundary(mcp_app, mcp_token)
        self.grok_reviewer_app = grok_reviewer_app
        self.readiness_check = readiness_check

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            await self.mcp_app(scope, receive, send)
            return
        if scope["type"] != "http":
            await _json_response(send, 404, {"error": "not_found"})
            return
        path = scope.get("path")
        if path == "/health":
            if scope.get("method") != "GET":
                await _json_response(
                    send,
                    405,
                    {"error": "method_not_allowed"},
                    extra_headers=((b"allow", b"GET"),),
                )
                return
            await _json_response(send, 200, {"status": "ok"})
            return
        if path == "/ready":
            if scope.get("method") != "GET":
                await _json_response(
                    send,
                    405,
                    {"error": "method_not_allowed"},
                    extra_headers=((b"allow", b"GET"),),
                )
                return
            ready = False
            if self.readiness_check is not None:
                try:
                    ready = bool(await anyio.to_thread.run_sync(self.readiness_check))
                except Exception:
                    ready = False
            await _json_response(
                send,
                200 if ready else 503,
                {
                    "checks": {"database": "ok" if ready else "unavailable"},
                    "status": "ready" if ready else "not_ready",
                },
            )
            return
        if path == "/mcp":
            await self.authenticated_mcp_app(scope, receive, send)
            return
        if path.startswith('/reviewer/') and self.grok_reviewer_app is not None:
            await self.grok_reviewer_app(scope, receive, send)
            return
        if path == "/webhooks/github":
            await self.webhook_app(scope, receive, send)
            return
        await _json_response(send, 404, {"error": "not_found"})


def create_composite_application(
    runtime,
    webhook_secret,
    mcp_token,
    *,
    public_hosts=(),
    actor_id="builder",
    grok_reviewer_app=None,
):
    if not isinstance(webhook_secret, str) or not webhook_secret:
        raise HubError("GITHUB_WEBHOOK_SECRET must be set and non-empty")
    hosts = [*LOCAL_ALLOWED_HOSTS]
    origins = [*LOCAL_ALLOWED_ORIGINS]
    for host in public_hosts:
        if not isinstance(host, str) or not host or any(char in host for char in "/\\\r\n"):
            raise HubError("Public MCP host must be a hostname without scheme or path")
        hosts.append(host)
        origins.append("https://" + host)
    remote_server = create_remote_mcp_server(runtime, actor_id)
    mcp_app = remote_server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=hosts,
            allowed_origins=origins,
        ),
        host="127.0.0.1",
    )

    def database_ready():
        with runtime.db.connect() as connection:
            return connection.execute("SELECT 1").fetchone() == (1,)

    application = CompositeApplication(
        GitHubWebhookApplication(runtime, webhook_secret),
        mcp_app,
        mcp_token,
        grok_reviewer_app,
        database_ready,
    )
    application.remote_server = remote_server
    return application
