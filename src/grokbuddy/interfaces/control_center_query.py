"""Read-only, task-scoped Control Center projections over Hub records."""

from __future__ import annotations

import base64
import binascii
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from grokbuddy.adapters.sqlite import SQLiteRepository
from grokbuddy.domain.model import HubError, NotFound, PermissionDenied
from grokbuddy.domain.review_policy import V1_DUAL_ROUND


MESSAGE_STAGES = frozenset({"PLAN", "PLAN_REVISION", "CODE", "TEST", "DELIVERY"})
PREVIEW_LIMIT = 1024 * 1024
SENSITIVE = re.compile(
    r"(?im)^\s*(?:authorization\s*:|[^\r\n]*(?:secret|token|password|api[_-]?key)\s*[:=])"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|\bBearer\s+[A-Za-z0-9._~+/-]{12,}"
    r"|\b[A-Za-z]:\\[^\s\r\n\"']*|\\\\[^\s\\]+\\[^\s\r\n\"']*"
    r"|(?<![A-Za-z0-9])/(?:home|Users|tmp|var|mnt|etc)/[^\s\r\n\"']*"
)


def safe_relative_path(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 500:
        return False
    if value.startswith("/") or "\\" in value or ":" in value:
        return False
    return (not any(ord(char) < 32 for char in value)
            and not value.lower().endswith((".log", ".trace"))
            and "logs" not in (part.lower() for part in value.split("/"))
            and all(part not in ("", ".", "..") for part in value.split("/")))


def display_text(value):
    if not isinstance(value, str):
        return ""
    return SENSITIVE.sub("[敏感内容已隐藏]", value)


def artifact_meta(artifact):
    if artifact is None:
        return None
    return {key: artifact[key] for key in
            ("id", "artifact_type", "size_bytes", "sha256", "created_at")}


def review_text(result):
    if not isinstance(result, dict):
        return None
    return {
        "summary": display_text(result.get("summary")),
        "timestamp": result.get("timestamp"),
        "blocker_category": result.get("blocker_category"),
        "comments": [display_text(x) for x in result.get("comments", [])
                     if isinstance(x, str)],
        "suggestions": [display_text(x) for x in result.get("suggestions", [])
                        if isinstance(x, str)],
        "recommendations": [display_text(x) for x in result.get("recommendations", [])
                            if isinstance(x, str)],
        "risks": [
            {"code": display_text(x.get("code")),
             "description": display_text(x.get("description")),
             "mitigation": display_text(x.get("mitigation")),
             "blocking": x.get("blocking")}
            for x in result.get("risks", []) if isinstance(x, dict)
        ],
        "findings": [
            {"title": display_text(x.get("title")),
             "description": display_text(x.get("description")),
             "finding": display_text(x.get("finding")),
             "impact": display_text(x.get("impact")),
             "recommendation": display_text(x.get("recommendation")),
             "severity": x.get("severity"), "blocking": x.get("blocking"),
             "category": display_text(x.get("category")),
             "proposed_changes": [display_text(change)
                                  for change in x.get("proposed_changes", [])
                                  if isinstance(change, str)],
             "evidence": display_text(x.get("evidence", {}).get("description"))
                         if isinstance(x.get("evidence"), dict) else ""}
            for x in result.get("findings", []) if isinstance(x, dict)
        ],
        "proposed_changes": [
            {"description": display_text(x.get("description")),
             "rationale": display_text(x.get("rationale"))}
            for x in result.get("proposed_changes", []) if isinstance(x, dict)
        ],
        "evidence": [
            {"description": display_text(x.get("description")),
             "kind": display_text(x.get("kind"))}
            for x in result.get("evidence", []) if isinstance(x, dict)
        ],
        "verifications": [
            {"finding_id": x.get("finding_id"), "outcome": x.get("outcome"),
             "reason": display_text(x.get("reason")),
             "evidence": display_text(x.get("evidence", {}).get("description"))
                         if isinstance(x.get("evidence"), dict) else ""}
            for x in result.get("verifications", []) if isinstance(x, dict)
        ],
    }


def review_label(request, review, v1):
    status = request["status"]
    if status in ("TIMED_OUT", "FAILED", "ESCALATED"):
        return "审核技术故障" if status != "ESCALATED" else "审核已中止"
    if review is None or status != "COMPLETED":
        return "审核中" if status == "IN_PROGRESS" else "等待审核"
    verdict = review["effective_verdict"]
    if not v1:
        return f"{verdict}（历史规则）"
    if request["review_round"] == 2 and verdict == "NEEDS_CHANGES":
        return "无效结果"
    plan = request["review_type"] == "PLAN_REVIEW"
    if request["review_round"] == 2 and verdict == "BLOCK":
        return "BLOCKED，等待 Human" if plan else "BLOCKED · 未验收通过"
    if verdict == "PASS":
        return "方案已通过" if plan else "审核通过"
    if verdict == "NEEDS_CHANGES":
        return "方案待修订" if plan else "代码待修改"
    return "R1 阻断意见，待修订" if plan else "R1 阻断意见，待修改"


class ControlCenterQuery:
    def __init__(self, runtime, reviewer_actor_id="grok-reviewer-b"):
        self.db = runtime.db
        self.store = runtime.store
        self.reviewer_actor_id = reviewer_actor_id

    @contextmanager
    def read(self):
        # Never initialize a DB or open a write transaction from a page request.
        connection = sqlite3.connect(self.db.path.as_uri() + "?mode=ro", uri=True)
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            yield SQLiteRepository(connection), connection
        finally:
            connection.close()

    @staticmethod
    def task(repo, task_id):
        if not isinstance(task_id, str) or not re.fullmatch(r"TASK-[A-Za-z0-9-]+", task_id):
            raise NotFound("Task not found")
        return repo.get("tasks", task_id)

    def list_tasks(self):
        with self.read() as (_, connection):
            rows = connection.execute(
                "SELECT data FROM tasks ORDER BY json_extract(data,'$.created_at') DESC,rowid DESC LIMIT 100"
            ).fetchall()
        return [
            {"id": x["id"], "state": x["state"], "created_at": x["created_at"],
             "completion_basis": x.get("completion_basis"),
             "decision_policy_version": x.get("decision_policy_version")}
            for raw, in rows for x in [json.loads(raw)]
        ]

    def _package(self, artifacts, task_id, artifact_id):
        artifact = artifacts.get(artifact_id)
        if not artifact or artifact["artifact_type"] != "FINAL_PACKAGE":
            return None
        try:
            value = json.loads(self.store.read(artifact["storage_pointer"], artifact["sha256"],
                                               artifact["size_bytes"]))
        except (HubError, ValueError, UnicodeError):
            return None
        return value if isinstance(value, dict) and value.get("task_id") == task_id else None

    def _result(self, artifacts, review):
        if review is None:
            return None
        if isinstance(review.get("result_snapshot"), dict):
            return review["result_snapshot"]
        artifact = artifacts.get(review.get("result_artifact_id"))
        if not artifact or artifact["artifact_type"] != "REVIEW_RESULT":
            return None
        try:
            return json.loads(self.store.read(artifact["storage_pointer"], artifact["sha256"],
                                              artifact["size_bytes"]))
        except (HubError, ValueError, UnicodeError):
            return None

    def _related(self, repo, task):
        task_id = task["id"]
        artifacts = {x["id"]: x for x in repo.find("artifacts", task_id=task_id)}
        requests = sorted(repo.find("review_requests", task_id=task_id),
                          key=lambda x: (0 if x["review_type"] == "PLAN_REVIEW" else 1,
                                         x["review_round"], x["created_at"], x["id"]))
        reviews = {x["review_request_id"]: x for x in repo.find("reviews", task_id=task_id)}
        invalid = {}
        for event in repo.find("audit_logs", task_id=task_id):
            if event["action"] == "VALIDATION_FAILURE" and event.get("request_id"):
                invalid[event["request_id"]] = display_text(
                    event.get("payload_summary", {}).get("code"))
        v1 = task.get("decision_policy_version") == V1_DUAL_ROUND
        rounds = []
        for request in requests:
            review = reviews.get(request["id"])
            result = self._result(artifacts, review)
            actor = review.get("reviewer_actor_id") if review else None
            stated_reviewer = result.get("reviewer") if isinstance(result, dict) else None
            genuine_grok = (actor == self.reviewer_actor_id
                            and isinstance(stated_reviewer, dict)
                            and stated_reviewer.get("type") == "grok_bot"
                            and stated_reviewer.get("id") == actor
                            and request["status"] == "COMPLETED")
            rounds.append({
                "id": request["id"], "type": request["review_type"],
                "round": request["review_round"], "status": request["status"],
                "failure_code": display_text(request.get("failure_code") or
                                             invalid.get(request["id"])),
                "created_at": request["created_at"], "started_at": request.get("started_at"),
                "completed_at": request.get("completed_at"),
                "input": artifact_meta(artifacts.get(request["input_artifact_id"])),
                "reported_verdict": review.get("reported_verdict") if review else None,
                "effective_verdict": review.get("effective_verdict") if review else None,
                "reviewer_id": actor,
                "reviewer_label": "GrokBot" if genuine_grok else actor,
                "review": review_text(result),
                "hub_applied_at": review.get("created_at") if review else None,
                "label": ("结果无效" if review is None
                          and request["status"] in ("PENDING", "IN_PROGRESS")
                          and request["id"] in invalid else
                          review_label(request, review, v1)),
            })
        messages = []
        for artifact in artifacts.values():
            if artifact["artifact_type"] != "WORKBUDDY_MESSAGE":
                continue
            try:
                value = json.loads(self.store.read(artifact["storage_pointer"], artifact["sha256"],
                                                   artifact["size_bytes"]))
            except (HubError, ValueError, UnicodeError):
                continue
            if isinstance(value, dict) and value.get("stage") in MESSAGE_STAGES and isinstance(value.get("body"), str):
                messages.append({"stage": value["stage"], "body": display_text(value["body"]),
                                 "created_at": artifact["created_at"], "actor_id": artifact["created_by"],
                                 "artifact": artifact_meta(artifact)})
        messages.sort(key=lambda x: (x["created_at"], x["artifact"]["id"]))
        packages = []
        for request in requests:
            if request["review_type"] != "FINAL_REVIEW":
                continue
            package = self._package(artifacts, task_id, request["input_artifact_id"])
            if package is None:
                continue
            files = []
            for item in package.get("generated_files", []):
                if not isinstance(item, dict) or not safe_relative_path(item.get("path")):
                    continue
                artifact = artifacts.get(item.get("artifact_id"))
                if (artifact and artifact["artifact_type"] == "SOURCE_FILE"
                        and artifact["sha256"] == item.get("sha256")):
                    files.append({"path": item["path"], "artifact": artifact_meta(artifact)})
            tests = []
            for item in package.get("test_results", []):
                if not isinstance(item, dict):
                    continue
                artifact = artifacts.get(item.get("artifact_id"))
                if (artifact and artifact["artifact_type"] == "TEST_RESULT"
                        and artifact["sha256"] == item.get("sha256")):
                    tests.append(artifact_meta(artifact))
            diff_ref = package.get("diff_artifact")
            diff = artifacts.get(diff_ref.get("artifact_id")) if isinstance(diff_ref, dict) else None
            packages.append({
                "round": request["review_round"], "request_id": request["id"],
                "artifact": artifact_meta(artifacts.get(request["input_artifact_id"])),
                "operation_method": display_text(package.get("operation_method"))
                                    if package.get("operation_method") else None,
                "generated_files": files, "tests": tests,
                "self_test": {
                    "status": display_text(package["self_test"].get("status")),
                    "summary": display_text(package["self_test"].get("summary")),
                } if isinstance(package.get("self_test"), dict) else None,
                "changed_files": [x if safe_relative_path(x) else "[受限路径已隐藏]"
                                  for x in package.get("changed_files", []) if isinstance(x, str)],
                "diff": artifact_meta(diff) if diff and diff["artifact_type"] == "DIFF" else None,
                "known_risks": [display_text(x) for x in package.get("known_risks", []) if isinstance(x, str)],
                "unverified_items": [display_text(x) for x in package.get("unverified_items", []) if isinstance(x, str)],
            })
        return artifacts, rounds, messages, packages

    def task_detail(self, task_id):
        with self.read() as (repo, _):
            task = self.task(repo, task_id)
            artifacts, rounds, messages, packages = self._related(repo, task)
            human = []
            for approval in sorted(repo.find("human_approvals", task_id=task_id),
                                   key=lambda item: (item.get("decision_at") or 0, item["id"])):
                reason = artifacts.get(approval.get("reason_artifact_id"))
                human.append({
                    "kind": approval.get("kind"), "status": approval.get("status"),
                    "decision_at": approval.get("decision_at"),
                    "reason": artifact_meta(reason) if reason and reason["artifact_type"] != "LOG" else None,
                })
            def at(kind, number):
                return next((x for x in rounds if x["type"] == kind and x["round"] == number), None)
            plan1, plan2 = at("PLAN_REVIEW", 1), at("PLAN_REVIEW", 2)
            final2 = at("FINAL_REVIEW", 2)
            v1 = task.get("decision_policy_version") == V1_DUAL_ROUND
            blocked_plan = (v1 and plan2 is not None and plan2["status"] == "COMPLETED"
                            and plan2["effective_verdict"] == "BLOCK")
            blocked_final = (v1 and final2 is not None and final2["status"] == "COMPLETED"
                             and final2["effective_verdict"] == "BLOCK")
            return {
                "task": {
                    "id": task_id, "state": task["state"], "created_at": task["created_at"],
                    "completion_basis": task.get("completion_basis"),
                    "gate_reason": display_text(task.get("gate_reason")),
                    "decision_policy_version": task.get("decision_policy_version"),
                    "original_task": artifact_meta(artifacts.get(task.get("original_task_id"))),
                },
                "rounds": rounds, "workbuddy_messages": messages, "packages": packages,
                "human_decisions": human,
                "plan_r2_blocked": {
                    "active": task["state"] == "PLAN_HUMAN_REVIEW",
                    "plan_v1": plan1["input"] if plan1 else None,
                    "grok_r1": plan1["review"] if plan1 else None,
                    "r1_reviewer_label": plan1["reviewer_label"] if plan1 else None,
                    "plan_v2": plan2["input"],
                    "r2_reason": plan2["review"],
                    "r2_reviewer_label": plan2["reviewer_label"],
                } if blocked_plan else None,
                "final_r2_blocked": {
                    "active": task["state"] == "FINAL_HUMAN_REVIEW",
                    "package": next((x for x in packages if x["round"] == 2), None),
                    "r2_reason": final2["review"],
                    "r2_reviewer_label": final2["reviewer_label"],
                    "acceptance": "未验收通过",
                } if blocked_final else None,
            }

    @staticmethod
    def _cursor(value):
        if value is None:
            return None
        try:
            decoded = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
            if (not isinstance(decoded, list) or len(decoded) != 3
                    or type(decoded[0]) is not int or decoded[0] < 0
                    or not all(isinstance(part, str) for part in decoded[1:])):
                raise ValueError
            return decoded
        except (ValueError, UnicodeError, binascii.Error) as exc:
            raise HubError("Invalid timeline cursor") from exc

    @staticmethod
    def _time_key(value):
        if type(value) is int:
            return value
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
                       * 1_000_000)
        except (AttributeError, ValueError, OverflowError):
            return 0

    def timeline(self, task_id, cursor=None):
        after = self._cursor(cursor)
        with self.read() as (repo, _):
            self.task(repo, task_id)
            audits = repo.find("audit_logs", task_id=task_id)
            task_events = repo.find("task_events", task_id=task_id)
            artifacts = repo.find("artifacts", task_id=task_id)
            requests = repo.find("review_requests", task_id=task_id)
            reviews = repo.find("reviews", task_id=task_id)
            workers = repo.find("worker_assignments", task_id=task_id)
            approvals = repo.find("human_approvals", task_id=task_id)
            findings = repo.find("finding_events", task_id=task_id)
        allowed_meta = {"artifact_id", "approval_id", "assignment_id", "review_round",
                        "generation", "code", "verdict", "delivery_channel", "worker_status"}
        entries = []
        def add(source, value, at, action, **fields):
            if at is None:
                return
            key = (self._time_key(at), source, value["id"])
            entries.append((key, {
                "id": value["id"], "source": source, "at": at,
                "action": action, **fields,
            }))
        for value in audits:
            metadata = {
                key: display_text(item) if isinstance(item, str) else item
                for key, item in value.get("payload_summary", {}).items()
                if key in allowed_meta and isinstance(item, (str, int, bool))
            }
            add("audit", value, value["timestamp"], value["action"],
                actor_type=value["actor_type"], actor_name=display_text(value["actor_name"]),
                old_state=value.get("old_state"), new_state=value.get("new_state"),
                request_id=value.get("request_id"), metadata=metadata)
        for value in task_events:
            add("task_event", value, value.get("at"), value["action"],
                old_state=value.get("old_state"), new_state=value.get("new_state"))
        for value in artifacts:
            add("artifact", value, value.get("created_at"), value["artifact_type"],
                metadata={"artifact_id": value["id"], "size_bytes": value["size_bytes"]})
        for value in requests:
            fields = {"request_id": value["id"],
                      "metadata": {"review_round": value["review_round"],
                                   "review_type": value["review_type"]}}
            add("review_request", value, value.get("created_at"), "REVIEW_REQUEST_CREATED",
                **fields)
            if value.get("completed_at"):
                add("review_request_result", value, value["completed_at"],
                    "REVIEW_REQUEST_" + value["status"], **fields)
        for value in reviews:
            add("review", value, value.get("created_at"), "REVIEW_APPLIED",
                request_id=value["review_request_id"],
                metadata={"verdict": value["effective_verdict"]})
        for value in workers:
            add("worker", value, value.get("offered_at"), "WORKER_OFFERED",
                metadata={"generation": value["generation"]})
        for value in approvals:
            add("human", value, value.get("decision_at"), "HUMAN_" + value["kind"],
                metadata={"approval_id": value["id"], "status": value["status"]})
        for value in findings:
            add("finding", value, value.get("at"),
                "FINDING_" + str(value.get("new_status", "UPDATED")),
                metadata={"finding_id": value["finding_id"]})
        entries.sort(key=lambda item: item[0])
        if after is not None:
            entries = [item for item in entries if item[0] > tuple(after)]
        page = entries[:100]
        next_cursor = None
        if len(entries) > 100:
            next_cursor = base64.urlsafe_b64encode(
                json.dumps(page[-1][0], separators=(",", ":")).encode()
            ).decode().rstrip("=")
        return {"events": [item[1] for item in page], "next_cursor": next_cursor}

    def artifact_bytes(self, task_id, artifact_id, *, preview=False):
        if not isinstance(artifact_id, str) or not re.fullmatch(r"ART-[A-Za-z0-9-]+", artifact_id):
            raise NotFound("Artifact not found")
        with self.read() as (repo, _):
            task = self.task(repo, task_id)
            artifacts, rounds, messages, packages = self._related(repo, task)
            artifact = artifacts.get(artifact_id)
            if artifact is None:
                raise NotFound("Artifact not found")
            allowed = {task.get("original_task_id")}
            allowed.update(x["input"]["id"] for x in rounds if x["input"])
            allowed.update(x["artifact"]["id"] for x in messages)
            for package in packages:
                allowed.update(x["id"] for x in package["tests"])
                allowed.update(x["artifact"]["id"] for x in package["generated_files"])
                if package["diff"]:
                    allowed.add(package["diff"]["id"])
            for approval in repo.find("human_approvals", task_id=task_id):
                allowed.add(approval.get("reason_artifact_id"))
            if artifact_id not in allowed or artifact["artifact_type"] in {"LOG", "REVIEW_RESULT"}:
                raise PermissionDenied("Artifact is outside Control Center scope")
            if preview and (artifact["size_bytes"] > PREVIEW_LIMIT or not (
                    artifact["mime_type"].startswith("text/")
                    or artifact["mime_type"] == "application/json")):
                raise HubError("Artifact cannot be previewed")
            content = self.store.read(artifact["storage_pointer"], artifact["sha256"],
                                      artifact["size_bytes"])
            try:
                decoded = content.decode("utf-8")
            except UnicodeError:
                decoded = None
            if decoded is None or SENSITIVE.search(decoded):
                raise PermissionDenied("Artifact contains restricted content")
            if preview:
                if decoded is None:
                    raise HubError("Artifact cannot be previewed")
                return artifact_meta(artifact), decoded
            return artifact_meta(artifact), content
