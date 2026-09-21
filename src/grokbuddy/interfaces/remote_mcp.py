"""Restricted read-only MCP surface for the Phase 4 HTTP transport."""

from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from grokbuddy.domain.model import HubError
from .gateway import ClientGateway
from .mcp import READ_ONLY


REMOTE_TOOL_NAMES = (
    "get_task",
    "get_task_status",
    "get_plan_review",
    "get_final_review",
    "list_pending_review_requests",
)


def _query(gateway, name, payload):
    try:
        return gateway.invoke_query(name, payload)
    except HubError as exc:
        raise ToolError(f"{exc.code}: {exc}") from exc


def create_remote_mcp_server(runtime, actor_id="builder"):
    """Create the five-tool read-only server used only by Remote MCP."""
    gateway = ClientGateway(runtime, actor_id)
    server = MCPServer(
        name="grokbuddy-hub-read-only",
        title="GrokBuddy Collaboration Hub Read-only Queries",
        description="Authenticated read-only Hub queries over Streamable HTTP.",
        instructions=(
            "This endpoint is read-only. It cannot create tasks, request reviews, "
            "submit artifacts, respond to findings, close tasks, or run workers."
        ),
        version="0.1.0",
        log_level="WARNING",
    )

    @server.tool(annotations=READ_ONLY)
    def get_task(task_id: str) -> dict[str, Any]:
        """Read the authoritative durable snapshot for a task."""
        return _query(gateway, "get_task", {"task_id": task_id})

    @server.tool(annotations=READ_ONLY)
    def get_task_status(task_id: str) -> dict[str, Any]:
        """Read compact task state without changing the Hub."""
        return _query(gateway, "get_task_status", {"task_id": task_id})

    @server.tool(annotations=READ_ONLY)
    def get_plan_review(review_request_id: str) -> dict[str, Any]:
        """Read one plan review request and its immutable result, if complete."""
        return _query(gateway, "get_plan_review", {
            "review_request_id": review_request_id,
        })

    @server.tool(annotations=READ_ONLY)
    def get_final_review(review_request_id: str) -> dict[str, Any]:
        """Read one final review request, result, and related findings."""
        return _query(gateway, "get_final_review", {
            "review_request_id": review_request_id,
        })

    @server.tool(annotations=READ_ONLY)
    def list_pending_review_requests() -> list[dict[str, Any]]:
        """List PENDING/IN_PROGRESS requests without claim, lease, or dispatch."""
        return _query(gateway, "list_pending_review_requests", {})

    return server
