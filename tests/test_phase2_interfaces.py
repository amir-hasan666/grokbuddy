import io
import json
import hashlib
import hmac
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from conftest import CONTRACTS
from grokbuddy.domain.model import HubError, PermissionDenied
from grokbuddy.interfaces.cli import main as cli_main
from grokbuddy.interfaces.gateway import ClientGateway, TOOL_NAMES
from grokbuddy.interfaces.http import JsonHttpApplication
from grokbuddy.interfaces.mcp import create_mcp_server
from grokbuddy.application.common import canonical
from grokbuddy.application.trigger import PHRASE


def key():
    return str(uuid4())


TRIGGER_KEY = 'test-only-placeholder-trigger_key-29'


def signed_create_payload(description):
    message = dict(principal_id='workbuddy-ingress', conversation_id=key(),
                   message_id=key(), turn_id=key(), message_role='user',
                   issued_at=time.time_ns() // 1000,
                   segments=[{'source': 'user_body', 'text': description}])
    raw = description.encode('utf-8')
    start = raw.index(PHRASE.encode('utf-8'))
    return dict(description=description, idempotency_key=key(), trigger_evidence={
        'message': message,
        'signature': hmac.new(TRIGGER_KEY.encode('utf-8'), canonical(message),
                              hashlib.sha256).hexdigest(),
        'body_sha256': hashlib.sha256(raw).hexdigest(), 'phrase': PHRASE,
        'start_byte': start, 'end_byte': start + len(PHRASE.encode('utf-8')),
    })


def invoke(gateway, name, **payload):
    return gateway.invoke(name, payload)


def create_with_plan(gateway):
    task = invoke(gateway, "create_task", description="Phase 2 本地入口测试", idempotency_key=key())
    plan = invoke(gateway, "submit_artifact", task_id=task["id"], artifact_type="PLAN",
                  content_text="A concrete local plan", idempotency_key=key())
    task = invoke(gateway, "submit_plan", task_id=task["id"], plan_artifact_id=plan["id"],
                  expected_version=task["version"], idempotency_key=key())
    return task, plan


def complete_plan(runtime, gateway, scenario="PASS"):
    task, _ = create_with_plan(gateway)
    request_key = key()
    receipt = invoke(gateway, "request_plan_review", task_id=task["id"],
                     expected_version=task["version"], idempotency_key=request_key)
    runtime.mock.configure(receipt["review_request_id"], scenario)
    return task["id"], receipt, request_key


def test_declared_phase2_tool_surface_is_exact():
    assert TOOL_NAMES == (
        "create_task", "get_task", "submit_plan", "request_plan_review", "get_plan_review",
        "respond_to_review", "submit_artifact", "request_final_review", "get_final_review",
        "get_task_status", "human_gate_decide", "close_task",
    )


def test_gateway_mock_roundtrip_keeps_receipt_and_query_separate(runtime):
    gateway = ClientGateway(runtime)
    task_id, receipt, request_key = complete_plan(runtime, gateway)
    rr = receipt["review_request_id"]
    assert receipt == {"review_request_id": rr, "status": "PENDING"}
    assert invoke(gateway, "get_task_status", task_id=task_id)["state"] == "PLAN_REVIEW_PENDING"
    assert invoke(gateway, "get_plan_review", review_request_id=rr)["review"] is None

    assert runtime.dispatcher.dispatch_one() == "SENT"
    assert invoke(gateway, "get_plan_review", review_request_id=rr)["request"]["status"] == "PENDING"
    assert runtime.mock.run_one() == "PASS"
    assert invoke(gateway, "get_plan_review", review_request_id=rr)["review"] is None
    assert runtime.events.handle_one() == "APPLIED"

    replay = invoke(gateway, "request_plan_review", task_id=task_id, expected_version=2,
                    idempotency_key=request_key)
    assert replay == receipt
    query = invoke(gateway, "get_plan_review", review_request_id=rr)
    assert query["request"]["status"] == "COMPLETED"
    assert query["review"]["effective_verdict"] == "PASS"
    assert invoke(gateway, "get_task_status", task_id=task_id)["state"] == "PLAN_APPROVED"


def test_final_review_response_and_second_round_complete_through_gateway(runtime):
    gateway = ClientGateway(runtime)
    task_id, plan_receipt, _ = complete_plan(runtime, gateway)
    runtime.tick()
    assert invoke(gateway, "get_plan_review", review_request_id=plan_receipt["review_request_id"])["review"]

    test_artifact = invoke(gateway, "submit_artifact", task_id=task_id, artifact_type="TEST_RESULT",
                           content_text="tests passed", idempotency_key=key())
    diff = invoke(gateway, "submit_artifact", task_id=task_id, artifact_type="DIFF",
                  content_text="first diff", idempotency_key=key())
    start = invoke(gateway, "get_task_status", task_id=task_id)
    first_payload = dict(
        task_id=task_id, test_artifact_id=test_artifact["id"], diff_artifact_id=diff["id"],
        expected_version=start["version"], idempotency_key=key(), begin_execution=True,
        change_scope="Local Phase 2 adapter", changed_files=["src/example.py"],
        self_test_summary="Local tests passed", known_risks=[], unverified_items=["External integrations"],
    )
    first = gateway.invoke("request_final_review", first_payload)
    runtime.mock.configure(first["review_request_id"], "NEEDS_CHANGES")
    runtime.tick()
    final = invoke(gateway, "get_final_review", review_request_id=first["review_request_id"])
    finding = final["findings"][0]
    assert final["request"]["status"] == "COMPLETED"
    assert final["review"]["effective_verdict"] == "NEEDS_CHANGES"

    evidence = invoke(gateway, "submit_artifact", task_id=task_id, artifact_type="DIFF",
                      content_text="remediation evidence", idempotency_key=key())
    status = invoke(gateway, "get_task_status", task_id=task_id)
    accepted = invoke(gateway, "respond_to_review", task_id=task_id,
                      review_id=final["review"]["id"], finding_id=finding["id"], action="accept",
                      expected_version=status["version"], idempotency_key=key())
    assert accepted["finding"]["status"] == "ACCEPTED"
    status = invoke(gateway, "get_task_status", task_id=task_id)
    response = invoke(gateway, "respond_to_review", task_id=task_id,
                      review_id=final["review"]["id"], finding_id=finding["id"], action="fix",
                      evidence_artifact_id=evidence["id"], expected_version=status["version"],
                      idempotency_key=key())
    assert response["finding"]["status"] == "FIXED"
    assert response["review_requested"] is False

    next_test = invoke(gateway, "submit_artifact", task_id=task_id, artifact_type="TEST_RESULT",
                       content_text="regression tests passed", idempotency_key=key())
    second_payload = dict(
        task_id=task_id, test_artifact_id=next_test["id"], diff_artifact_id=evidence["id"],
        expected_version=0,
        idempotency_key=key(), begin_execution=False, change_scope="Remediation",
        changed_files=["src/example.py"], self_test_summary="Regression tests passed",
        known_risks=[], unverified_items=["External integrations"],
    )
    # Finding version is separate from Task version; query the authoritative Task projection.
    second_payload["expected_version"] = invoke(gateway, "get_task_status", task_id=task_id)["version"]
    second = gateway.invoke("request_final_review", second_payload)
    runtime.mock.configure(second["review_request_id"], "PASS", verifications=[{
        "finding_id": finding["id"], "outcome": "VERIFIED", "reason": "Retested through Phase 2",
        "evidence": {"artifact_id": evidence["id"], "locator": "fix", "description": "Local evidence"},
    }])
    runtime.tick()
    assert invoke(gateway, "get_task_status", task_id=task_id)["state"] == "DONE"
    assert invoke(gateway, "get_final_review", review_request_id=second["review_request_id"])["findings"][0]["status"] == "VERIFIED"

    replay = gateway.invoke("request_final_review", second_payload)
    assert replay == second == {"review_request_id": second["review_request_id"], "status": "PENDING"}


def test_respond_to_review_rejects_wrong_review_binding(runtime):
    gateway = ClientGateway(runtime)
    task_id, receipt, _ = complete_plan(runtime, gateway)
    runtime.tick()
    with pytest.raises(HubError, match="Finding does not belong"):
        invoke(gateway, "respond_to_review", task_id=task_id, review_id="REV-not-real",
               finding_id="FND-not-real", action="accept", expected_version=4, idempotency_key=key())


def test_strict_inputs_and_review_query_types(runtime):
    gateway = ClientGateway(runtime)
    with pytest.raises(HubError, match="Unknown tool fields"):
        invoke(gateway, "create_task", description="x", idempotency_key=key(), actor_id="human")
    with pytest.raises(HubError, match="profile"):
        invoke(gateway, "create_task", description="x", idempotency_key=key(), profile=7)
    task_id, receipt, _ = complete_plan(runtime, gateway)
    with pytest.raises(HubError, match="does not match"):
        invoke(gateway, "get_final_review", review_request_id=receipt["review_request_id"])
    with pytest.raises(HubError, match="Exactly one"):
        invoke(gateway, "submit_artifact", task_id=task_id, artifact_type="LOG",
               idempotency_key=key(), content_text="x", content_base64="eA==")


def test_close_task_uses_existing_human_cancel_guard(runtime):
    builder = ClientGateway(runtime, "builder")
    task = invoke(builder, "create_task", description="cancel me", idempotency_key=key())
    payload = dict(task_id=task["id"], reason="Human ended local task",
                   expected_version=task["version"], idempotency_key=key())
    with pytest.raises(PermissionDenied):
        builder.invoke("close_task", payload)
    human = ClientGateway(runtime, "human")
    closed = human.invoke("close_task", payload)
    assert closed["state"] == "CANCELLED"
    assert human.invoke("close_task", payload) == closed


def call_wsgi(app, path, payload, method="POST"):
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    body = b"".join(app({"REQUEST_METHOD": method, "PATH_INFO": path,
                         "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw)}, start_response))
    return captured, json.loads(body)


def test_http_adapter_calls_same_gateway_and_maps_errors(runtime):
    app = JsonHttpApplication(ClientGateway(runtime))
    response, body = call_wsgi(app, "/v1/tools/create_task", {
        "description": "HTTP 中文任务", "idempotency_key": key(),
    })
    assert response["status"] == "200 OK"
    assert body["result"]["state"] == "NEW"

    response, body = call_wsgi(app, "/v1/tools/create_task", b"not-json")
    assert response["status"] == "400 Bad Request"
    assert body["error"]["code"] == "INVALID_JSON"

    response, _ = call_wsgi(app, "/v1/tools/no-such-tool", {})
    assert response["status"] == "404 Not Found"
    response, _ = call_wsgi(app, "/v1/tools/get_task", {}, method="GET")
    assert response["status"] == "405 Method Not Allowed"


def test_cli_persists_between_invocations_without_running_review_inline(runtime, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv('GROKBUDDY_TRIGGER_SOURCE_KEY', TRIGGER_KEY)
    runtime_dir = tmp_path / "CLI 中文 runtime"
    create_file = tmp_path / "create.json"
    create_file.write_text(json.dumps(signed_create_payload('CLI task ' + PHRASE)), encoding="utf-8")
    common = ["--runtime-dir", str(runtime_dir), "--contracts-dir", str(CONTRACTS),
              "--actor", "workbuddy-ingress"]
    assert cli_main([*common, "create_task", "--input", str(create_file)]) == 0
    created = json.loads(capsys.readouterr().out)["result"]

    get_file = tmp_path / "get.json"
    get_file.write_text(json.dumps({"task_id": created["id"]}), encoding="utf-8")
    assert cli_main([*common, "get_task", "--input", str(get_file)]) == 0
    queried = json.loads(capsys.readouterr().out)["result"]
    assert queried["id"] == created["id"]

    assert cli_main([*common, "worker-once"]) == 0
    tick = json.loads(capsys.readouterr().out)["result"]
    assert tick == {"dispatch": None, "event": None, "mock": None, "timeouts": 0}


@pytest.mark.anyio
async def test_mcp_legacy_client_lists_exact_tools_and_keeps_plan_request_pending(runtime):
    server = create_mcp_server(runtime)
    async with Client(server, mode="legacy", raise_exceptions=True) as client:
        listed = await client.list_tools()
        assert tuple(tool.name for tool in listed.tools) == TOOL_NAMES
        assert str(client.protocol_version) == "2025-11-25"

        created_call = await client.call_tool("create_task", {
            "description": "MCP legacy client task",
            "idempotency_key": key(),
        })
        assert not created_call.is_error
        task = created_call.structured_content
        plan_call = await client.call_tool("submit_artifact", {
            "task_id": task["id"],
            "artifact_type": "PLAN",
            "idempotency_key": key(),
            "content_text": "MCP plan",
        })
        plan = plan_call.structured_content
        submitted_call = await client.call_tool("submit_plan", {
            "task_id": task["id"],
            "plan_artifact_id": plan["id"],
            "approved_scope": {
                "summary": "MCP Phase 2 plan scope",
                "files": ["local.txt"],
            },
            "expected_version": task["version"],
            "idempotency_key": key(),
        })
        submitted = submitted_call.structured_content
        review_call = await client.call_tool("request_plan_review", {
            "task_id": task["id"],
            "expected_version": submitted["version"],
            "idempotency_key": key(),
        })
        assert review_call.structured_content == {
            "review_request_id": review_call.structured_content["review_request_id"],
            "status": "PENDING",
        }
        query = await client.call_tool("get_plan_review", {
            "review_request_id": review_call.structured_content["review_request_id"],
        })
        assert query.structured_content["request"]["status"] == "PENDING"
        assert query.structured_content["review"] is None

        cancel_target = (await client.call_tool("create_task", {
            "description": "MCP human cancel target",
            "idempotency_key": key(),
        })).structured_content
        closed = (await client.call_tool("close_task", {
            "task_id": cancel_target["id"],
            "reason": "Human cancelled from the MCP client",
            "expected_version": cancel_target["version"],
            "idempotency_key": key(),
        })).structured_content
        assert closed["state"] == "CANCELLED"
        cancelled_audit = runtime.hub.audit_log(cancel_target["id"])
        assert cancelled_audit[-1]["actor_id"] == "human"
        assert cancelled_audit[-1]["new_state"] == "CANCELLED"


@pytest.mark.anyio
async def test_mcp_stdio_subprocess_handshake_and_create_task(tmp_path, monkeypatch):
    monkeypatch.setenv('GROKBUDDY_TRIGGER_SOURCE_KEY', TRIGGER_KEY)
    root = Path(__file__).resolve().parents[1]
    runtime_dir = tmp_path / "MCP stdio runtime"
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            str(root / "scripts" / "grokbuddy_mcp.py"),
            "--runtime-dir", str(runtime_dir),
            "--contracts-dir", str(CONTRACTS),
            "--actor", "workbuddy-ingress",
        ],
        cwd=str(root),
        env={**os.environ, 'GROKBUDDY_TRIGGER_SOURCE_KEY': TRIGGER_KEY},
    )
    payload = signed_create_payload('WorkBuddy-compatible stdio smoke ' + PHRASE)
    async with Client(params, mode="legacy", raise_exceptions=True,
                      read_timeout_seconds=10) as client:
        listed = await client.list_tools()
        assert tuple(tool.name for tool in listed.tools) == TOOL_NAMES
        result = await client.call_tool("create_task", payload)
        assert not result.is_error
        assert result.structured_content["state"] == "NEW"
        assert result.structured_content["id"].startswith("TASK-")
        task_id = result.structured_content["id"]

    # A new stdio process reading the same Hub database must replay the
    # durable command receipt rather than create a second Task.
    async with Client(params, mode="legacy", raise_exceptions=True,
                      read_timeout_seconds=10) as client:
        replay = await client.call_tool("create_task", payload)
        assert replay.structured_content["id"] == task_id
