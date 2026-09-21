"""Loopback-first WSGI HTTP fallback for the Phase 2 client tool surface."""

import argparse
import json
from pathlib import Path
from wsgiref.simple_server import make_server

from grokbuddy.domain.model import Conflict, HubError, NotFound, PermissionDenied
from grokbuddy.infrastructure.runtime import LocalRuntime
from .gateway import ClientGateway, TOOL_NAMES


MAX_HTTP_BODY = 64 * 1024 * 1024


def _default_contracts():
    return Path(__file__).resolve().parents[3] / "docs" / "contracts"


class JsonHttpApplication:
    """A small WSGI adapter; authentication remains outside this local fallback."""

    def __init__(self, gateway):
        self.gateway = gateway

    @staticmethod
    def _response(start_response, status, body):
        data = json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
        start_response(status, [("Content-Type", "application/json; charset=utf-8"),
                                ("Content-Length", str(len(data)))])
        return [data]

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        if environ.get("REQUEST_METHOD") != "POST":
            return self._response(start_response, "405 Method Not Allowed", {
                "ok": False, "error": {"code": "METHOD_NOT_ALLOWED", "message": "POST is required"}
            })
        prefix = "/v1/tools/"
        tool_name = path[len(prefix):] if path.startswith(prefix) else ""
        if tool_name not in TOOL_NAMES or "/" in tool_name:
            return self._response(start_response, "404 Not Found", {
                "ok": False, "error": {"code": "NOT_FOUND", "message": "Unknown tool route"}
            })
        try:
            raw_length = environ.get("CONTENT_LENGTH", "")
            if not raw_length:
                raise HubError("Content-Length is required")
            length = int(raw_length)
            if length < 0 or length > MAX_HTTP_BODY:
                raise HubError("HTTP request body is outside the size limit")
            raw = environ["wsgi.input"].read(length)
            payload = json.loads(raw.decode("utf-8"))
            result = self.gateway.invoke(tool_name, payload)
            return self._response(start_response, "200 OK", {"ok": True, "result": result})
        except (ValueError, UnicodeError, json.JSONDecodeError):
            return self._response(start_response, "400 Bad Request", {
                "ok": False, "error": {"code": "INVALID_JSON", "message": "Body must be UTF-8 JSON"}
            })
        except HubError as exc:
            status = "422 Unprocessable Entity"
            if isinstance(exc, NotFound):
                status = "404 Not Found"
            elif isinstance(exc, PermissionDenied):
                status = "403 Forbidden"
            elif isinstance(exc, Conflict):
                status = "409 Conflict"
            return self._response(start_response, status, {
                "ok": False, "error": {"code": exc.code, "message": str(exc)}
            })


def _parser():
    parser = argparse.ArgumentParser(description="GrokBuddy local HTTP fallback")
    parser.add_argument("--runtime-dir", required=True)
    parser.add_argument("--contracts-dir", default=str(_default_contracts()))
    parser.add_argument("--actor", default="builder", help="Configured local simulation principal")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("The unauthenticated fallback server may bind only to loopback")
    runtime = LocalRuntime(args.runtime_dir, args.contracts_dir)
    app = JsonHttpApplication(ClientGateway(runtime, args.actor))
    with make_server(args.host, args.port, app) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
