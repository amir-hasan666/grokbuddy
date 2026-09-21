"""Explicit Phase 4 loopback smoke test; never prints the MCP bearer token."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import sqlite3
import subprocess
import sys
import time

import httpx2
from mcp import Client, ClientSession
from mcp.client.stdio import StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "var" / "github-manual"
PORT = 8788
BASE = f"http://127.0.0.1:{PORT}"
READ_TOOLS = (
    "get_task",
    "get_task_status",
    "get_plan_review",
    "get_final_review",
    "list_pending_review_requests",
)
FORBIDDEN_TOOLS = (
    "create_task",
    "submit_plan",
    "request_plan_review",
    "respond_to_review",
    "submit_artifact",
    "request_final_review",
    "close_task",
)


def _has_listener():
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=0.3):
            return True
    except OSError:
        return False


def _listener_pids():
    output = subprocess.check_output(["netstat", "-ano"], text=True)
    pids = []
    for line in output.splitlines():
        fields = line.split()
        if (
            len(fields) >= 5
            and fields[0] == "TCP"
            and fields[1] == f"127.0.0.1:{PORT}"
            and fields[3] == "LISTENING"
        ):
            pids.append(int(fields[4]))
    return pids


def _wait_for_listener(process, timeout=20):
    deadline = time.monotonic() + timeout
    observed = []
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Composite server exited with code {process.returncode}")
        if _has_listener():
            pids = _listener_pids()
            observed = pids
            if len(pids) == 1:
                return pids[0]
            if len(pids) > 1:
                raise RuntimeError("8788 has multiple listeners")
        time.sleep(0.1)
    raise RuntimeError(f"Composite server did not exclusively bind 8788; observed={observed}")


def _wait_port_free(timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _has_listener() and not _listener_pids():
            return True
        time.sleep(0.1)
    return False


def _stop_owned_process(process):
    if process is None or process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.send_signal(signal.SIGINT)
        process.wait(timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def _restore_original(env):
    if not _wait_port_free():
        return {"status": "blocked", "reason": "8788 occupied by another process"}
    command = [
        sys.executable,
        str(ROOT / "scripts" / "grokbuddy_github.py"),
        "--runtime-dir",
        str(RUNTIME),
        "serve",
        "--secret-env",
        "GITHUB_WEBHOOK_SECRET",
        "--host",
        "127.0.0.1",
        "--port",
        str(PORT),
    ]
    flags = (
        subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        if os.name == "nt"
        else 0
    )
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return {"status": "failed", "exit_code": process.returncode}
        pids = _listener_pids()
        if len(pids) == 1:
            # On Windows this venv launcher spawns the interpreter that owns
            # the socket, so its PID is not the actual listener PID.
            try:
                import urllib.error
                import urllib.request

                urllib.request.urlopen(BASE + "/webhooks/github", timeout=2)
            except urllib.error.HTTPError as exc:
                if exc.code == 405:
                    return {"status": "restored", "pid": pids[0]}
            except OSError:
                pass
        time.sleep(0.1)
    return {"status": "failed", "reason": "original listener did not bind"}


def _snapshot():
    connection = sqlite3.connect(f"file:{RUNTIME / 'hub.db'}?mode=ro", uri=True)
    try:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        values = {
            table: connection.execute(
                f"SELECT id, data FROM {table} ORDER BY id"
            ).fetchall()
            for table in tables
        }
        payload = json.dumps(values, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "counts": {table: len(rows) for table, rows in values.items()},
        }
    finally:
        connection.close()


def _sample_ids():
    connection = sqlite3.connect(f"file:{RUNTIME / 'hub.db'}?mode=ro", uri=True)
    try:
        tasks = [json.loads(row[0]) for row in connection.execute("SELECT data FROM tasks")]
        requests = [
            json.loads(row[0])
            for row in connection.execute("SELECT data FROM review_requests")
        ]
    finally:
        connection.close()
    for task in tasks:
        related = [request for request in requests if request["task_id"] == task["id"]]
        plan = next((item for item in related if item["review_type"] == "PLAN_REVIEW"), None)
        final = next((item for item in related if item["review_type"] == "FINAL_REVIEW"), None)
        if plan and final:
            return task["id"], plan["id"], final["id"]
    raise RuntimeError("No existing Task with both Plan and Final Review test data")


def _business_data(result):
    value = result.structured_content
    if value is None:
        value = json.loads(result.content[0].text)
    if isinstance(value, dict) and set(value) == {"result"}:
        return value["result"]
    return value


async def _exercise(token, ids):
    task_id, plan_id, final_id = ids
    args = {
        "get_task": {"task_id": task_id},
        "get_task_status": {"task_id": task_id},
        "get_plan_review": {"review_request_id": plan_id},
        "get_final_review": {"review_request_id": final_id},
        "list_pending_review_requests": {},
    }
    requests = []
    response_content_types = []

    async def request_hook(request):
        if request.url.path == "/mcp":
            requests.append(request.method)

    async def response_hook(response):
        if response.request.url.path == "/mcp":
            response_content_types.append(response.headers.get("content-type", ""))

    async with httpx2.AsyncClient(timeout=10) as client:
        health = await client.get(BASE + "/health")
        webhook = await client.get(BASE + "/webhooks/github")
        missing = await client.post(BASE + "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        wrong = await client.post(
            BASE + "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
            headers={"authorization": "Bearer deliberately-wrong"},
        )
        disabled = await client.get(
            BASE + "/mcp", headers={"authorization": f"Bearer {token}"}
        )
        if not (
            health.status_code == 200
            and health.json() == {"status": "ok"}
            and webhook.status_code == 405
            and missing.status_code == wrong.status_code == 401
            and disabled.status_code == 405
        ):
            raise RuntimeError("Live health, webhook reachability, or MCP auth check failed")

    stdio_config = StdioServerParameters(
        command=sys.executable,
        args=[
            str(ROOT / "scripts" / "grokbuddy_mcp.py"),
            "--runtime-dir",
            str(RUNTIME),
        ],
    )
    async with Client(stdio_config, mode="legacy") as stdio:
        stdio_tools = tuple(tool.name for tool in (await stdio.list_tools()).tools)
        stdio_results = {
            name: _business_data(await stdio.call_tool(name, args[name]))
            for name in READ_TOOLS[:-1]
        }
    if len(stdio_tools) != 11:
        raise RuntimeError("The existing stdio MCP tool surface changed")

    before = _snapshot()
    async with httpx2.AsyncClient(
        headers={"authorization": f"Bearer {token}"},
        timeout=10,
        event_hooks={"request": [request_hook], "response": [response_hook]},
    ) as client:
        async with streamable_http_client(
            BASE + "/mcp", http_client=client, terminate_on_close=False
        ) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as remote:
                initialized = await remote.initialize()
                listed = tuple(tool.name for tool in (await remote.list_tools()).tools)
                if listed != READ_TOOLS:
                    raise RuntimeError("Remote tool surface is not the exact five-tool allowlist")
                remote_results = {
                    name: _business_data(await remote.call_tool(name, args[name]))
                    for name in READ_TOOLS
                }
                for name in FORBIDDEN_TOOLS:
                    try:
                        forbidden = await remote.call_tool(name, {})
                    except MCPError:
                        continue
                    if not forbidden.is_error:
                        raise RuntimeError(f"Forbidden Remote MCP tool was callable: {name}")
    after = _snapshot()
    if before != after:
        raise RuntimeError("Hub business tables changed during Remote MCP reads")
    for name in READ_TOOLS[:-1]:
        if remote_results[name] != stdio_results[name]:
            raise RuntimeError(f"stdio/Remote MCP business data differs for {name}")
    if any(method != "POST" for method in requests):
        raise RuntimeError("Official client used non-POST MCP method")
    if not response_content_types or any(
        not content_type.startswith("application/json")
        for content_type in response_content_types
    ):
        raise RuntimeError("MCP did not use JSON-response Streamable HTTP")
    return {
        "health": health.status_code,
        "webhook_get": webhook.status_code,
        "mcp_missing_token": missing.status_code,
        "mcp_wrong_token": wrong.status_code,
        "mcp_get_with_token": disabled.status_code,
        "mcp_protocol_version": initialized.protocol_version,
        "transport": "official SDK Streamable HTTP; stateless; JSON response; POST only",
        "mcp_post_count": len(requests),
        "remote_tools": listed,
        "forbidden_tools_rejected": len(FORBIDDEN_TOOLS),
        "stdio_tools": len(stdio_tools),
        "stdio_remote_query_parity": True,
        "pending_query_count": len(remote_results["list_pending_review_requests"]),
        "hub_tables_unchanged": True,
        "hub_snapshot_sha256": before["sha256"],
        "task_count": before["counts"]["tasks"],
        "review_request_count": before["counts"]["review_requests"],
        "github_comment_projection_count": before["counts"]["github_comment_projections"],
        "mock_job_count": before["counts"]["mock_jobs"],
    }


def main():
    if not os.environ.get("GITHUB_WEBHOOK_SECRET"):
        raise RuntimeError("GITHUB_WEBHOOK_SECRET is required")
    if _has_listener():
        raise RuntimeError("8788 is occupied; do not stop an unowned listener")
    token = os.environ.get("GROKBUDDY_MCP_TOKEN") or secrets.token_urlsafe(48)
    env = os.environ.copy()
    env["GROKBUDDY_MCP_TOKEN"] = token
    command = [
        sys.executable,
        str(ROOT / "scripts" / "grokbuddy_composite.py"),
        "--runtime-dir",
        str(RUNTIME),
        "--host",
        "127.0.0.1",
        "--port",
        str(PORT),
    ]
    flags = (
        subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        if os.name == "nt"
        else 0
    )
    process = None
    report = {}
    try:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        listener_pid = _wait_for_listener(process)
        report = asyncio.run(_exercise(token, _sample_ids()))
        report["composite_listener_pid"] = listener_pid
        report["result"] = "LOCAL PASS"
    except Exception as exc:
        report = {"result": "LOCAL FAILED", "reason": str(exc)}
    finally:
        _stop_owned_process(process)
        restore_env = env.copy()
        restore_env.pop("GROKBUDDY_MCP_TOKEN", None)
        report["original_webhook_listener"] = _restore_original(restore_env)
        report["token_source"] = (
            "existing environment" if os.environ.get("GROKBUDDY_MCP_TOKEN") else "ephemeral test process"
        )
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report.get("result") == "LOCAL PASS" and report["original_webhook_listener"].get("status") == "restored" else 1


if __name__ == "__main__":
    raise SystemExit(main())
