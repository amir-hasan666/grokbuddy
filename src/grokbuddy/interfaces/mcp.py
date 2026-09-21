"""WorkBuddy-facing MCP adapter for the existing Phase 2 gateway.

The server intentionally uses stdio by default.  Every tool delegates to the
same ClientGateway used by the HTTP and CLI fallbacks, so MCP does not own any
business state or review lifecycle logic.
"""

import argparse
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from grokbuddy.domain.model import HubError
from grokbuddy.infrastructure.runtime import LocalRuntime
from .gateway import ClientGateway


READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True,
                            openWorldHint=False)
IDEMPOTENT_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True,
                                   openWorldHint=False)
HUMAN_CANCEL = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True,
                               openWorldHint=False)


def _default_contracts():
    return Path(__file__).resolve().parents[3] / "docs" / "contracts"


def _call(gateway, name, payload):
    try:
        return gateway.invoke(name, payload)
    except HubError as exc:
        # Deliberate domain/input failures are safe for the MCP client to see;
        # unexpected exceptions remain hidden by the SDK.
        raise ToolError(f"{exc.code}: {exc}") from exc


def create_mcp_server(runtime, actor_id="builder", human_actor_id="human"):
    """Create an MCP server over one durable LocalRuntime.

    The normal tool surface is bound to the configured Builder simulation
    principal.  human_gate_decide and close_task are deliberately bound to a
    separate, fixed Human simulation principal and cannot be selected from
    tool input.
    """

    gateway = ClientGateway(runtime, actor_id)
    human_gateway = ClientGateway(runtime, human_actor_id)
    server = MCPServer(
        name="grokbuddy-hub",
        title="GrokBuddy Collaboration Hub",
        description="Local asynchronous collaboration workflow tools for WorkBuddy.",
        instructions=(
            "Review requests only enqueue durable work and return PENDING. "
            "Use the matching get_* tool to query completion."
        ),
        version="0.1.0",
        log_level="WARNING",
    )

    @server.tool(annotations=IDEMPOTENT_WRITE)
    def create_task(
        description: str,
        idempotency_key: str,
        profile: str = "generic",
        profile_version: str = "1.0",
        trigger_evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create only from a signed current WorkBuddy user message with an exact trigger."""
        return _call(gateway, "create_task", {
            "description": description,
            "idempotency_key": idempotency_key,
            "profile": profile,
            "profile_version": profile_version,
            "trigger_evidence": trigger_evidence,
        })

    @server.tool(annotations=READ_ONLY)
    def get_task(task_id: str) -> dict[str, Any]:
        """Read the authoritative durable snapshot for a task."""
        return _call(gateway, "get_task", {"task_id": task_id})

    @server.tool(annotations=IDEMPOTENT_WRITE)
    def submit_plan(
        task_id: str,
        plan_artifact_id: str,
        expected_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Attach a previously submitted plan artifact to a task."""
        return _call(gateway, "submit_plan", {
            "task_id": task_id,
            "plan_artifact_id": plan_artifact_id,
            "expected_version": expected_version,
            "idempotency_key": idempotency_key,
        })

    @server.tool(annotations=IDEMPOTENT_WRITE)
    def request_plan_review(
        task_id: str,
        expected_version: int,
        idempotency_key: str,
        reviewer_id: str | None = None,
    ) -> dict[str, Any]:
        """Enqueue an asynchronous plan review and immediately return PENDING."""
        payload = {
            "task_id": task_id,
            "expected_version": expected_version,
            "idempotency_key": idempotency_key,
        }
        if reviewer_id is not None:
            payload["reviewer_id"] = reviewer_id
        return _call(gateway, "request_plan_review", payload)

    @server.tool(annotations=READ_ONLY)
    def get_plan_review(review_request_id: str) -> dict[str, Any]:
        """Query a plan review request separately from review submission."""
        return _call(gateway, "get_plan_review", {"review_request_id": review_request_id})

    @server.tool(annotations=IDEMPOTENT_WRITE)
    def respond_to_review(
        task_id: str,
        review_id: str,
        finding_id: str,
        action: str,
        expected_version: int,
        idempotency_key: str,
        evidence_artifact_id: str | None = None,
    ) -> dict[str, Any]:
        """Accept, reject, or fix one stable finding; this never starts a new review."""
        payload = {
            "task_id": task_id,
            "review_id": review_id,
            "finding_id": finding_id,
            "action": action,
            "expected_version": expected_version,
            "idempotency_key": idempotency_key,
        }
        if evidence_artifact_id is not None:
            payload["evidence_artifact_id"] = evidence_artifact_id
        return _call(gateway, "respond_to_review", payload)

    @server.tool(annotations=IDEMPOTENT_WRITE)
    def submit_artifact(
        task_id: str,
        artifact_type: str,
        idempotency_key: str,
        content_text: str | None = None,
        content_base64: str | None = None,
        mime_type: str = "text/plain",
    ) -> dict[str, Any]:
        """Store immutable text or base64 content and return its controlled pointer."""
        payload = {
            "task_id": task_id,
            "artifact_type": artifact_type,
            "idempotency_key": idempotency_key,
            "mime_type": mime_type,
        }
        if content_text is not None:
            payload["content_text"] = content_text
        if content_base64 is not None:
            payload["content_base64"] = content_base64
        return _call(gateway, "submit_artifact", payload)

    @server.tool(annotations=IDEMPOTENT_WRITE)
    def request_final_review(
        task_id: str,
        test_artifact_id: str,
        diff_artifact_id: str,
        expected_version: int,
        idempotency_key: str,
        begin_execution: bool,
        change_scope: str,
        changed_files: list[str],
        self_test_summary: str,
        known_risks: list[str],
        unverified_items: list[str],
        reviewer_id: str | None = None,
    ) -> dict[str, Any]:
        """Submit the final package and enqueue review, returning only PENDING."""
        payload = {
            "task_id": task_id,
            "test_artifact_id": test_artifact_id,
            "diff_artifact_id": diff_artifact_id,
            "expected_version": expected_version,
            "idempotency_key": idempotency_key,
            "begin_execution": begin_execution,
            "change_scope": change_scope,
            "changed_files": changed_files,
            "self_test_summary": self_test_summary,
            "known_risks": known_risks,
            "unverified_items": unverified_items,
        }
        if reviewer_id is not None:
            payload["reviewer_id"] = reviewer_id
        return _call(gateway, "request_final_review", payload)

    @server.tool(annotations=READ_ONLY)
    def get_final_review(review_request_id: str) -> dict[str, Any]:
        """Query a final review, including findings, separately from submission."""
        return _call(gateway, "get_final_review", {"review_request_id": review_request_id})

    @server.tool(annotations=READ_ONLY)
    def get_task_status(task_id: str) -> dict[str, Any]:
        """Read the compact task state, version, active review, and deadline."""
        return _call(gateway, "get_task_status", {"task_id": task_id})

    @server.tool(annotations=HUMAN_CANCEL)
    def human_gate_decide(
        task_id: str,
        decision: str,
        reason: str,
        expected_version: int,
        idempotency_key: str,
        acknowledged_findings: list[str] | None = None,
        modification_scope: dict[str, Any] | None = None,
        finding_ids: list[str] | None = None,
        extra_review_budget: int = 0,
        new_deadline_at: int | None = None,
    ) -> dict[str, Any]:
        """Decide ACCEPT/MODIFY/CONTINUE/ABORT as the configured Human principal."""
        payload = {
            "task_id": task_id,
            "decision": decision,
            "reason": reason,
            "expected_version": expected_version,
            "idempotency_key": idempotency_key,
            "extra_review_budget": extra_review_budget,
        }
        if acknowledged_findings is not None:
            payload["acknowledged_findings"] = acknowledged_findings
        if modification_scope is not None:
            payload["modification_scope"] = modification_scope
        if finding_ids is not None:
            payload["finding_ids"] = finding_ids
        if new_deadline_at is not None:
            payload["new_deadline_at"] = new_deadline_at
        return _call(human_gateway, "human_gate_decide", payload)

    @server.tool(annotations=HUMAN_CANCEL)
    def close_task(
        task_id: str,
        reason: str,
        expected_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Cancel a task as the configured Human principal; this is not review PASS."""
        return _call(human_gateway, "close_task", {
            "task_id": task_id,
            "reason": reason,
            "expected_version": expected_version,
            "idempotency_key": idempotency_key,
        })

    return server


def _parser():
    parser = argparse.ArgumentParser(description="GrokBuddy Hub MCP server (stdio)")
    parser.add_argument("--runtime-dir", required=True, help="Local Hub data directory")
    parser.add_argument("--contracts-dir", default=str(_default_contracts()))
    parser.add_argument("--actor", default="builder", help="Fixed local Builder simulation principal")
    parser.add_argument("--human-actor", default="human", help="Fixed local Human principal for close_task")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    runtime = LocalRuntime(args.runtime_dir, args.contracts_dir)
    server = create_mcp_server(runtime, args.actor, args.human_actor)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
