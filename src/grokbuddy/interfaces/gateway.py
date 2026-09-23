"""Transport-neutral WorkBuddy fallback tool facade.

The facade is intentionally synchronous only at the command boundary. Review
requests return their durable PENDING receipt; workers and result queries stay
separate.
"""

import base64
import binascii
import hashlib

from grokbuddy.domain.model import HubError


TOOL_NAMES = (
    "create_task",
    "get_task",
    "submit_plan",
    "request_plan_review",
    "get_plan_review",
    "respond_to_review",
    "submit_artifact",
    "record_workbuddy_message",
    "request_final_review",
    "get_final_review",
    "get_task_status",
    "human_gate_decide",
    "close_task",
)

REMOTE_QUERY_NAMES = (
    "get_task",
    "get_task_status",
    "get_plan_review",
    "get_final_review",
    "list_pending_review_requests",
)


def _derived_key(key, operation):
    return "phase2:" + hashlib.sha256(f"{key}\0{operation}".encode("utf-8")).hexdigest()


def _strict(payload, required, optional=()):
    if not isinstance(payload, dict):
        raise HubError("Tool input must be a JSON object")
    required, optional = set(required), set(optional)
    missing = required - set(payload)
    unknown = set(payload) - required - optional
    if missing:
        raise HubError("Missing tool fields: " + ", ".join(sorted(missing)))
    if unknown:
        raise HubError("Unknown tool fields: " + ", ".join(sorted(unknown)))


def _text(payload, name, *, allow_empty=False):
    value = payload.get(name)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise HubError(f"{name} must be a non-empty string")
    return value


def _integer(payload, name):
    value = payload.get(name)
    if type(value) is not int or value < 0:
        raise HubError(f"{name} must be a non-negative integer")
    return value


def _string_list(payload, name):
    value = payload.get(name)
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise HubError(f"{name} must be an array of non-empty strings")
    return value


class ClientGateway:
    """Map one configured local principal to the existing Hub application API."""

    def __init__(self, runtime, actor_id="builder"):
        if not isinstance(actor_id, str) or not actor_id:
            raise ValueError("A configured actor_id is required")
        self.runtime = runtime
        self.hub = runtime.hub
        self.actor_id = actor_id

    def invoke(self, tool_name, payload):
        if tool_name not in TOOL_NAMES:
            raise HubError("Unknown client tool")
        return getattr(self, "_" + tool_name)(payload)

    def invoke_query(self, tool_name, payload):
        """Invoke only the fixed read-only query surface used by Remote MCP."""
        if tool_name not in REMOTE_QUERY_NAMES:
            raise HubError("Unknown remote query tool")
        return getattr(self, "_" + tool_name)(payload)

    def _create_task(self, payload):
        _strict(payload, {"description", "idempotency_key"},
                {"profile", "profile_version", "trigger_evidence"})
        profile = payload.get("profile", "generic")
        profile_version = payload.get("profile_version", "1.0")
        if not isinstance(profile, str) or not profile or not isinstance(profile_version, str) or not profile_version:
            raise HubError("profile and profile_version must be non-empty strings")
        return self.hub.create_task(
            self.actor_id,
            _text(payload, "description"),
            _text(payload, "idempotency_key"),
            profile,
            profile_version,
            payload.get("trigger_evidence"),
        )

    def _get_task(self, payload):
        _strict(payload, {"task_id"})
        return self.hub.get_task(_text(payload, "task_id"))

    def _submit_plan(self, payload):
        _strict(payload, {"task_id", "plan_artifact_id", "expected_version", "idempotency_key"},
                {"approved_scope"})
        task_id = _text(payload, "task_id")
        key = _text(payload, "idempotency_key")
        started = self.hub.move(
            self.actor_id,
            task_id,
            "begin_plan",
            _integer(payload, "expected_version"),
            _derived_key(key, "begin-plan"),
        )
        return self.hub.submit_plan(
            self.actor_id,
            task_id,
            _text(payload, "plan_artifact_id"),
            started["version"],
            _derived_key(key, "submit-plan"),
            approved_scope=payload.get("approved_scope"),
        )

    def _request_plan_review(self, payload):
        _strict(payload, {"task_id", "expected_version", "idempotency_key"}, {"reviewer_id"})
        reviewer_id = payload.get("reviewer_id", self.runtime.default_reviewer_actor_id)
        if not isinstance(reviewer_id, str) or not reviewer_id:
            raise HubError("reviewer_id must be a non-empty string")
        return self.hub.request_review(
            self.actor_id,
            _text(payload, "task_id"),
            "PLAN_REVIEW",
            reviewer_id,
            _integer(payload, "expected_version"),
            _text(payload, "idempotency_key"),
        )

    def _review(self, payload, expected_type):
        _strict(payload, {"review_request_id"})
        result = self.hub.get_review(_text(payload, "review_request_id"))
        if result["request"]["review_type"] != expected_type:
            raise HubError("Review request type does not match query")
        return result

    def _get_plan_review(self, payload):
        return self._review(payload, "PLAN_REVIEW")

    def _respond_to_review(self, payload):
        _strict(
            payload,
            {"task_id", "review_id", "finding_id", "action", "expected_version", "idempotency_key"},
            {"evidence_artifact_id"},
        )
        task_id = _text(payload, "task_id")
        review_id = _text(payload, "review_id")
        finding_id = _text(payload, "finding_id")
        action = _text(payload, "action")
        if action not in ("accept", "reject", "fix"):
            raise HubError("action must be accept, reject, or fix")
        matches = [item for item in self.hub.list_findings(task_id) if item["id"] == finding_id]
        if not matches or matches[0]["review_id"] != review_id:
            raise HubError("Finding does not belong to the supplied review")
        evidence_id = payload.get("evidence_artifact_id")
        if action in ("reject", "fix") and not isinstance(evidence_id, str):
            raise HubError("Evidence is required for reject or fix")
        expected_version = _integer(payload, "expected_version")
        key = _text(payload, "idempotency_key")
        if action == "fix":
            task = self.hub.move(
                self.actor_id,
                task_id,
                "execute",
                expected_version,
                _derived_key(key, "begin-remediation"),
            )
            expected_version = task["version"]
        finding = self.hub.respond_finding(
            self.actor_id,
            finding_id,
            action,
            evidence_id,
            expected_version,
            _derived_key(key, "respond-finding"),
        )
        return {"review_id": review_id, "finding": finding, "review_requested": False}

    def _submit_artifact(self, payload):
        _strict(
            payload,
            {"task_id", "artifact_type", "idempotency_key"},
            {"content_text", "content_base64", "mime_type"},
        )
        text_present = "content_text" in payload
        base64_present = "content_base64" in payload
        if text_present == base64_present:
            raise HubError("Exactly one of content_text or content_base64 is required")
        if text_present:
            content = _text(payload, "content_text", allow_empty=True).encode("utf-8")
        else:
            try:
                content = base64.b64decode(_text(payload, "content_base64", allow_empty=True), validate=True)
            except (binascii.Error, ValueError) as exc:
                raise HubError("content_base64 is invalid") from exc
        mime = payload.get("mime_type", "text/plain")
        if not isinstance(mime, str) or not mime:
            raise HubError("mime_type must be a non-empty string")
        return self.hub.submit_artifact(
            self.actor_id,
            _text(payload, "task_id"),
            _text(payload, "artifact_type"),
            content,
            _text(payload, "idempotency_key"),
            mime,
        )

    def _record_workbuddy_message(self, payload):
        _strict(payload, {"task_id", "stage", "body", "idempotency_key"})
        return self.hub.record_workbuddy_message(
            self.actor_id, _text(payload, "task_id"), _text(payload, "stage"),
            _text(payload, "body"), _text(payload, "idempotency_key"))

    def _artifact_ref(self, artifact_id):
        artifact = self.hub.get_artifact(artifact_id)
        return {"artifact_id": artifact["id"], "sha256": artifact["sha256"]}

    def _request_final_review(self, payload):
        _strict(
            payload,
            {
                "task_id", "test_artifact_id", "diff_artifact_id", "expected_version",
                "idempotency_key", "begin_execution", "change_scope", "changed_files",
                "self_test_summary", "known_risks", "unverified_items",
            },
            {"reviewer_id", "operation_method", "generated_files"},
        )
        if type(payload["begin_execution"]) is not bool:
            raise HubError("begin_execution must be a boolean")
        reviewer_id = payload.get("reviewer_id", self.runtime.default_reviewer_actor_id)
        if not isinstance(reviewer_id, str) or not reviewer_id:
            raise HubError("reviewer_id must be a non-empty string")
        task_id = _text(payload, "task_id")
        key = _text(payload, "idempotency_key")
        expected_version = _integer(payload, "expected_version")
        if payload["begin_execution"]:
            executing = self.hub.move(
                self.actor_id,
                task_id,
                "execute",
                expected_version,
                _derived_key(key, "begin-execution"),
            )
            expected_version = executing["version"]
        tested = self.hub.self_test(
            self.actor_id,
            task_id,
            _text(payload, "test_artifact_id"),
            True,
            expected_version,
            _derived_key(key, "self-test"),
        )
        profile = self.hub.profile_snapshot(
            self.actor_id,
            task_id,
            _derived_key(key, "profile-snapshot"),
        )
        task = self.hub.get_task(task_id)
        # On a replay, use the frozen responses above rather than the task's later
        # mutable projection to reconstruct the same package and command digest.
        package = {
            "protocol_version": "v1",
            "task_id": task_id,
            "content_revision": tested["content_revision"],
            "original_task": self._artifact_ref(task["original_task_id"]),
            "approved_plan": self._artifact_ref(task["approved_plan_id"]),
            "change_scope": _text(payload, "change_scope"),
            "changed_files": _string_list(payload, "changed_files"),
            "diff_artifact": self._artifact_ref(_text(payload, "diff_artifact_id")),
            "test_results": [self._artifact_ref(_text(payload, "test_artifact_id"))],
            "self_test": {"status": "PASS", "summary": _text(payload, "self_test_summary")},
            "known_risks": _string_list(payload, "known_risks"),
            "unverified_items": _string_list(payload, "unverified_items"),
            "review_profile": task["profile"],
            "review_profile_version": task["profile_version"],
            "profile_sha256": profile["sha256"],
            "profile_artifact_id": profile["id"],
        }
        if "operation_method" in payload:
            package["operation_method"] = _text(payload, "operation_method")
        if "generated_files" in payload:
            files = payload["generated_files"]
            if not isinstance(files, list) or not all(
                    isinstance(item, dict) and set(item) == {"path", "artifact_id"}
                    and all(isinstance(value, str) and value for value in item.values())
                    for item in files):
                raise HubError("generated_files must contain path and artifact_id")
            package["generated_files"] = [
                {"path": item["path"], **self._artifact_ref(item["artifact_id"])}
                for item in files
            ]
        self.hub.submit_final_package(
            self.actor_id,
            task_id,
            package,
            tested["version"],
            _derived_key(key, "submit-final-package"),
        )
        return self.hub.request_review(
            self.actor_id,
            task_id,
            "FINAL_REVIEW",
            reviewer_id,
            tested["version"] + 1,
            _derived_key(key, "request-final-review"),
        )

    def _get_final_review(self, payload):
        result = self._review(payload, "FINAL_REVIEW")
        findings = self.hub.list_findings(result["request"]["task_id"])
        result["findings"] = findings
        result["created_findings"] = [
            item for item in findings if item["review_id"] == result["request"]["review_id"]
        ]
        return result

    def _get_task_status(self, payload):
        _strict(payload, {"task_id"})
        task = self.hub.get_task(_text(payload, "task_id"))
        return {
            "task_id": task["id"],
            "state": task["state"],
            "version": task["version"],
            "content_revision": task["content_revision"],
            "active_review_request_id": task["active_rr_id"],
            "escalation_reason": task["escalation_reason"],
            "deadline_at": task["deadline_at"],
        }

    def _list_pending_review_requests(self, payload):
        _strict(payload, set())
        return self.hub.list_pending_review_requests()

    def _human_gate_decide(self, payload):
        _strict(
            payload,
            {"task_id", "decision", "reason", "expected_version", "idempotency_key"},
            {"acknowledged_findings", "modification_scope", "finding_ids",
             "extra_review_budget", "new_deadline_at"},
        )
        acknowledged = payload.get("acknowledged_findings")
        finding_ids = payload.get("finding_ids")
        if acknowledged is not None:
            acknowledged = _string_list(payload, "acknowledged_findings")
        if finding_ids is not None:
            finding_ids = _string_list(payload, "finding_ids")
        extra_budget = payload.get("extra_review_budget", 0)
        if type(extra_budget) is not int or extra_budget < 0:
            raise HubError("extra_review_budget must be a non-negative integer")
        new_deadline_at = payload.get("new_deadline_at")
        if new_deadline_at is not None and (type(new_deadline_at) is not int or new_deadline_at < 0):
            raise HubError("new_deadline_at must be a non-negative integer")
        modification_scope = payload.get("modification_scope")
        if modification_scope is not None and not isinstance(modification_scope, dict):
            raise HubError("modification_scope must be an object")
        return self.hub.human_gate_decide(
            self.actor_id,
            _text(payload, "task_id"),
            _text(payload, "decision"),
            _text(payload, "reason"),
            _integer(payload, "expected_version"),
            _text(payload, "idempotency_key"),
            acknowledged_findings=acknowledged,
            modification_scope=modification_scope,
            finding_ids=finding_ids,
            extra_review_budget=extra_budget,
            new_deadline_at=new_deadline_at,
        )

    def _close_task(self, payload):
        _strict(payload, {"task_id", "reason", "expected_version", "idempotency_key"})
        return self.hub.cancel(
            self.actor_id,
            _text(payload, "task_id"),
            _text(payload, "reason"),
            _integer(payload, "expected_version"),
            _text(payload, "idempotency_key"),
        )
