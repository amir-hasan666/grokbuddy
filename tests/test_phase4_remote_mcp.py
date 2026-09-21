import hashlib
import hmac
import io
import json

import anyio
import httpx2
import pytest
from mcp import Client, ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError

from conftest import Flow
from grokbuddy.domain.model import HubError
from grokbuddy.interfaces.composite import create_composite_application
from grokbuddy.interfaces.gateway import ClientGateway, TOOL_NAMES
from grokbuddy.interfaces.github import GitHubWebhookApplication
from grokbuddy.interfaces.mcp import create_mcp_server
from grokbuddy.interfaces.remote_mcp import REMOTE_TOOL_NAMES


WEBHOOK_SECRET = 'test-only-placeholder-webhook_secret-22'
MCP_TOKEN = 'test-only-placeholder-mcp_token-23'


def _payload(revision):
    return {
        "repository": {"id": 1372874264, "full_name": "amir-hasan666/grokbuddy"},
        "sender": {"id": 13579},
        "ref": "refs/heads/phase4-read-only",
        "after": revision,
    }


def _body(payload):
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _signature(body):
    return "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()


def _call_wsgi(app, body, *, delivery, signature):
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/webhooks/github",
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": "application/json",
        "wsgi.input": io.BytesIO(body),
        "HTTP_X_GITHUB_DELIVERY": delivery,
        "HTTP_X_GITHUB_EVENT": "push",
        "HTTP_X_HUB_SIGNATURE_256": signature,
    }
    response = b"".join(app(environ, start_response))
    return int(captured["status"].split(" ", 1)[0]), json.loads(response)


def _business_snapshot(runtime):
    with runtime.db.connect() as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        return {
            table: connection.execute(
                f"SELECT id, data FROM {table} ORDER BY id"
            ).fetchall()
            for table in tables
        }


def _result_data(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


def _prepare_review_data(runtime):
    flow = Flow(runtime)
    flow.plan()
    plan_request_id = flow.request("PLAN_REVIEW")
    flow.drive()
    flow.move("execute")
    flow.package()
    final_request_id = flow.request("FINAL_REVIEW")
    return flow.id, plan_request_id, final_request_id


def test_pending_query_uses_existing_active_statuses_and_stable_shape(runtime):
    task_id, _, final_request_id = _prepare_review_data(runtime)

    assert runtime.hub.list_pending_review_requests() == [
        {
            "id": final_request_id,
            "task_id": task_id,
            "review_type": "FINAL_REVIEW",
            "status": "PENDING",
        }
    ]


def test_composite_refuses_to_create_public_mcp_without_token(runtime):
    with pytest.raises(HubError, match="GROKBUDDY_MCP_TOKEN"):
        create_composite_application(runtime, WEBHOOK_SECRET, "")


def test_public_host_allowlist_keeps_sdk_rebinding_protection(runtime):
    public_host = "existing-phase4.trycloudflare.com"
    composite = create_composite_application(
        runtime, WEBHOOK_SECRET, MCP_TOKEN, public_hosts=[public_host]
    )

    async def exercise():
        transport = httpx2.ASGITransport(app=composite)
        async with composite.mcp_app.router.lifespan_context(composite.mcp_app):
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://127.0.0.1:8788"
            ) as client:
                payload = {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
                common = {"authorization": f"Bearer {MCP_TOKEN}"}
                rejected = await client.post(
                    "/mcp",
                    json=payload,
                    headers={**common, "host": "unlisted.trycloudflare.com"},
                )
                accepted = await client.post(
                    "/mcp",
                    json=payload,
                    headers={
                        **common,
                        "host": public_host,
                        "origin": "https://" + public_host,
                    },
                )
                return rejected.status_code, accepted.status_code

    rejected, accepted = anyio.run(exercise)
    assert rejected == 421
    assert accepted != 421


def test_composite_preserves_webhook_status_and_side_effects(runtime):
    direct = GitHubWebhookApplication(runtime, WEBHOOK_SECRET)
    composite = create_composite_application(runtime, WEBHOOK_SECRET, MCP_TOKEN)
    body = _body(_payload("a" * 40))

    direct_status, direct_body = _call_wsgi(
        direct,
        body,
        delivery="phase4-direct-valid",
        signature=_signature(body),
    )

    async def exercise():
        transport = httpx2.ASGITransport(app=composite)
        async with httpx2.AsyncClient(
            transport=transport, base_url="http://127.0.0.1:8788"
        ) as client:
            health = await client.get("/health")
            valid = await client.post(
                "/webhooks/github",
                content=body,
                headers={
                    "content-type": "application/json",
                    "x-github-delivery": "phase4-composite-valid",
                    "x-github-event": "push",
                    "x-hub-signature-256": _signature(body),
                },
            )
            invalid = await client.post(
                "/webhooks/github",
                content=body,
                headers={
                    "content-type": "application/json",
                    "x-github-delivery": "phase4-composite-invalid",
                    "x-github-event": "push",
                    "x-hub-signature-256": "sha256=" + "0" * 64,
                },
            )
            return health, valid, invalid

    health, valid, invalid = anyio.run(exercise)
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert valid.status_code == direct_status == 202
    assert valid.json()["result"]["status"] == direct_body["result"]["status"] == "IGNORED"
    assert invalid.status_code == 401
    assert invalid.json()["error"]["code"] == "AUTHENTICATION_FAILURE"
    with runtime.db.connect() as connection:
        assert len(connection.execute("SELECT id FROM github_events").fetchall()) == 2


def test_composite_preserves_oversize_webhook_rejection(runtime):
    direct = GitHubWebhookApplication(runtime, WEBHOOK_SECRET)
    composite = create_composite_application(runtime, WEBHOOK_SECRET, MCP_TOKEN)
    captured = {}
    direct_body = b"".join(direct({
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/webhooks/github",
        "CONTENT_LENGTH": str(1024 * 1024 + 1),
        "wsgi.input": io.BytesIO(b""),
    }, lambda status, headers: captured.update(status=status, headers=headers)))

    async def exercise():
        transport = httpx2.ASGITransport(app=composite)
        async with httpx2.AsyncClient(
            transport=transport, base_url="http://127.0.0.1:8788"
        ) as client:
            return await client.post(
                "/webhooks/github",
                content=b"",
                headers={"content-length": str(1024 * 1024 + 1)},
            )

    response = anyio.run(exercise)
    assert response.status_code == int(captured["status"].split(" ", 1)[0]) == 413
    assert response.content == direct_body


def test_composite_signed_synchronize_preserves_review_request_side_effect(runtime):
    flow = Flow(runtime)
    flow.executing()
    flow.package()
    runtime.github_bindings.bind_pull_request(
        repository_id=1372874264,
        repository_full_name="amir-hasan666/grokbuddy",
        pull_request_number=2,
        task_id=flow.id,
        hub_pointer_base="hub://phase4-test",
    )
    composite = create_composite_application(runtime, WEBHOOK_SECRET, MCP_TOKEN)
    payload = {
        "repository": {"id": 1372874264, "full_name": "amir-hasan666/grokbuddy"},
        "sender": {"id": 13579},
        "action": "synchronize",
        "number": 2,
        "pull_request": {"head": {"sha": "b" * 40}},
    }
    body = _body(payload)

    async def exercise():
        transport = httpx2.ASGITransport(app=composite)
        async with httpx2.AsyncClient(
            transport=transport, base_url="http://127.0.0.1:8788"
        ) as client:
            return await client.post(
                "/webhooks/github",
                content=body,
                headers={
                    "content-type": "application/json",
                    "x-github-delivery": "phase4-composite-synchronize",
                    "x-github-event": "pull_request",
                    "x-hub-signature-256": _signature(body),
                },
            )

    response = anyio.run(exercise)
    assert response.status_code == 202
    result = response.json()["result"]
    assert result["status"] == "APPLIED"
    assert result["effect"]["status"] == "PENDING"
    request = runtime.hub.get_review(result["effect"]["review_request_id"])["request"]
    assert request["status"] == "PENDING"
    assert request["review_type"] == "FINAL_REVIEW"
    assert flow.task["state"] == "FINAL_REVIEW_PENDING"


def test_remote_auth_surface_query_parity_and_no_business_writes(runtime, caplog):
    task_id, plan_request_id, final_request_id = _prepare_review_data(runtime)
    composite = create_composite_application(runtime, WEBHOOK_SECRET, MCP_TOKEN)
    before = _business_snapshot(runtime)

    async def exercise():
        transport = httpx2.ASGITransport(app=composite)
        async with httpx2.AsyncClient(
            transport=transport, base_url="http://127.0.0.1:8788"
        ) as unauthenticated:
            missing = await unauthenticated.post(
                "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"}
            )
            wrong = await unauthenticated.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
                headers={"authorization": "Bearer wrong"},
            )
            disabled = await unauthenticated.get(
                "/mcp", headers={"authorization": f"Bearer {MCP_TOKEN}"}
            )

        async with composite.mcp_app.router.lifespan_context(composite.mcp_app):
            async with httpx2.AsyncClient(
                transport=transport,
                base_url="http://127.0.0.1:8788",
                headers={"authorization": f"Bearer {MCP_TOKEN}"},
            ) as authenticated:
                async with streamable_http_client(
                    "http://127.0.0.1:8788/mcp",
                    http_client=authenticated,
                    terminate_on_close=False,
                ) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as remote:
                        initialized = await remote.initialize()
                        tools = await remote.list_tools()
                        remote_results = {
                            "get_task": _result_data(await remote.call_tool(
                                "get_task", {"task_id": task_id}
                            )),
                            "get_task_status": _result_data(await remote.call_tool(
                                "get_task_status", {"task_id": task_id}
                            )),
                            "get_plan_review": _result_data(await remote.call_tool(
                                "get_plan_review", {"review_request_id": plan_request_id}
                            )),
                            "get_final_review": _result_data(await remote.call_tool(
                                "get_final_review", {"review_request_id": final_request_id}
                            )),
                            "list_pending_review_requests": _result_data(
                                await remote.call_tool("list_pending_review_requests", {})
                            ),
                        }
                        forbidden = {}
                        for name in (
                            "create_task",
                            "submit_plan",
                            "request_plan_review",
                            "respond_to_review",
                            "submit_artifact",
                            "request_final_review",
                            "human_gate_decide",
                            "close_task",
                        ):
                            try:
                                forbidden[name] = await remote.call_tool(name, {})
                            except MCPError:
                                forbidden[name] = None
        return missing, wrong, disabled, initialized, tools, remote_results, forbidden

    missing, wrong, disabled, initialized, tools, remote_results, forbidden = anyio.run(exercise)
    assert missing.status_code == wrong.status_code == 401
    assert missing.json() == wrong.json() == {"error": "unauthorized"}
    assert disabled.status_code == 405
    assert initialized.protocol_version
    assert tuple(tool.name for tool in tools.tools) == REMOTE_TOOL_NAMES
    assert all(result is None or result.is_error is True for result in forbidden.values())

    gateway = ClientGateway(runtime)
    expected = {
        "get_task": gateway.invoke("get_task", {"task_id": task_id}),
        "get_task_status": gateway.invoke("get_task_status", {"task_id": task_id}),
        "get_plan_review": gateway.invoke(
            "get_plan_review", {"review_request_id": plan_request_id}
        ),
        "get_final_review": gateway.invoke(
            "get_final_review", {"review_request_id": final_request_id}
        ),
        "list_pending_review_requests": gateway.invoke_query(
            "list_pending_review_requests", {}
        ),
    }
    remote_results["list_pending_review_requests"] = remote_results[
        "list_pending_review_requests"
    ]["result"]
    assert remote_results == expected
    assert _business_snapshot(runtime) == before
    assert MCP_TOKEN not in caplog.text
    assert "create_task" not in {tool.name for tool in tools.tools}
    assert TOOL_NAMES == (
        "create_task", "get_task", "submit_plan", "request_plan_review",
            "get_plan_review", "respond_to_review", "submit_artifact",
            "request_final_review", "get_final_review", "get_task_status",
            "human_gate_decide", "close_task",
        )


def test_existing_stdio_mcp_query_results_match_remote_query_layer(runtime):
    task_id, plan_request_id, final_request_id = _prepare_review_data(runtime)
    gateway = ClientGateway(runtime)

    async def exercise():
        async with Client(create_mcp_server(runtime), mode="legacy") as stdio:
            return {
                "get_task": _result_data(await stdio.call_tool(
                    "get_task", {"task_id": task_id}
                )),
                "get_task_status": _result_data(await stdio.call_tool(
                    "get_task_status", {"task_id": task_id}
                )),
                "get_plan_review": _result_data(await stdio.call_tool(
                    "get_plan_review", {"review_request_id": plan_request_id}
                )),
                "get_final_review": _result_data(await stdio.call_tool(
                    "get_final_review", {"review_request_id": final_request_id}
                )),
            }

    stdio_results = anyio.run(exercise)
    assert stdio_results == {
        "get_task": gateway.invoke_query("get_task", {"task_id": task_id}),
        "get_task_status": gateway.invoke_query("get_task_status", {"task_id": task_id}),
        "get_plan_review": gateway.invoke_query(
            "get_plan_review", {"review_request_id": plan_request_id}
        ),
        "get_final_review": gateway.invoke_query(
            "get_final_review", {"review_request_id": final_request_id}
        ),
    }
