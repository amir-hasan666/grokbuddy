"""Dedicated local WorkBuddy Worker MCP; Phase 2 and remote MCP stay unchanged."""

import argparse
from pathlib import Path
from typing import Any

from mcp.server import MCPServer

from grokbuddy.infrastructure.runtime import LocalRuntime
from .gateway import ClientGateway
from .mcp import IDEMPOTENT_WRITE, READ_ONLY, _call


WORKER_TOOL_NAMES = (
    'list_available_tasks', 'get_task', 'claim_task', 'submit_artifact', 'report_progress',
    'complete_task',
)
WORKER_ACTOR_ID = 'workbuddy-worker'


def create_worker_mcp_server(runtime):
    hub = runtime.hub
    gateway = ClientGateway(runtime, WORKER_ACTOR_ID)
    server = MCPServer(
        name='grokbuddy-worker',
        title='GrokBuddy WorkBuddy Worker',
        description='Local Task claim and Artifact upload for the WorkBuddy Worker.',
        instructions='Call list_available_tasks, get_task, claim_task, submit_artifact, report_progress, then complete_task.',
        version='0.1.0',
        log_level='WARNING',
    )

    @server.tool(annotations=READ_ONLY)
    def list_available_tasks() -> list[dict[str, Any]]:
        """List unclaimed, unexpired Task offers for WorkBuddy."""
        return _call_worker(lambda: hub.list_available_worker_tasks(WORKER_ACTOR_ID))

    @server.tool(annotations=READ_ONLY)
    def get_task(task_id: str) -> dict[str, Any]:
        """Read an offered Task and its original instruction before claiming."""
        return _call_worker(lambda: hub.get_worker_task(WORKER_ACTOR_ID, task_id))

    @server.tool(annotations=IDEMPOTENT_WRITE)
    def claim_task(task_id: str, expected_version: int, idempotency_key: str) -> dict[str, Any]:
        """Atomically claim an offered Task for the configured Worker principal."""
        return _call_worker(lambda: hub.claim_task(
            WORKER_ACTOR_ID, task_id, expected_version, idempotency_key))

    @server.tool(annotations=IDEMPOTENT_WRITE)
    def submit_artifact(task_id: str, artifact_type: str, idempotency_key: str,
                        content_text: str, mime_type: str = 'text/plain') -> dict[str, Any]:
        """Upload UTF-8 file content into the immutable Hub Artifact Store after claim."""
        return _call(gateway, 'submit_artifact', {
            'task_id': task_id, 'artifact_type': artifact_type,
            'idempotency_key': idempotency_key, 'content_text': content_text,
            'mime_type': mime_type,
        })

    @server.tool(annotations=IDEMPOTENT_WRITE)
    def report_progress(task_id: str, summary: str, idempotency_key: str) -> dict[str, Any]:
        """Record a short Worker progress summary after claim; does not request review."""
        return _call_worker(lambda: hub.report_worker_progress(
            WORKER_ACTOR_ID, task_id, summary, idempotency_key))

    @server.tool(annotations=IDEMPOTENT_WRITE)
    def complete_task(task_id: str, artifact_id: str, expected_version: int,
                      idempotency_key: str) -> dict[str, Any]:
        """Complete claimed WorkBuddy execution using its uploaded evidence."""
        return _call_worker(lambda: hub.complete_worker_task(
            WORKER_ACTOR_ID, task_id, artifact_id, expected_version, idempotency_key))

    return server


def _call_worker(action):
    from mcp.server.mcpserver.exceptions import ToolError
    from grokbuddy.domain.model import HubError

    try:
        return action()
    except HubError as exc:
        raise ToolError(f'{exc.code}: {exc}') from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description='GrokBuddy local WorkBuddy Worker MCP (stdio)')
    parser.add_argument('--runtime-dir', required=True)
    parser.add_argument('--contracts-dir', default=str(Path(__file__).resolve().parents[3] / 'docs' / 'contracts'))
    args = parser.parse_args(argv)
    runtime = LocalRuntime(args.runtime_dir, args.contracts_dir)
    create_worker_mcp_server(runtime).run(transport='stdio')


if __name__ == '__main__':
    main()
