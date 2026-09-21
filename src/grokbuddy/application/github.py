"""Phase 3 GitHub communication projection and webhook event use-cases.

These services are deliberately outside the domain model.  GitHub is an
ingress/projection carrier; Hub state, ReviewRequest status, and verdicts stay
authoritative in the existing application services.
"""

from __future__ import annotations

import json

from grokbuddy.domain.model import Conflict, HubError, Role
from .common import Services, audit, digest, uid


FINAL_TRIGGER_EVENT = "pull_request"
FINAL_TRIGGER_ACTION = "synchronize"
_SAFE_TRANSPORT_METADATA = {
    "retry_after_seconds", "rate_limit_reset", "rate_limit_remaining",
    "rate_limit_resource", "github_request_id",
}


def _bounded_text(value, maximum=500):
    value = " ".join(str(value or "").split())
    return value[:maximum]


def _safe_header(value, maximum):
    if not isinstance(value, str):
        return None
    return " ".join(value.split())[:maximum]


def _transport_failure(exc):
    code = _safe_header(getattr(exc, "code", None), 80) or type(exc).__name__[:80]
    retryable = bool(getattr(exc, "retryable", True))
    status = getattr(exc, "http_status", None)
    status = status if type(status) is int and 100 <= status <= 599 else None
    raw_metadata = getattr(exc, "safe_metadata", {})
    metadata = {}
    if isinstance(raw_metadata, dict):
        for key in _SAFE_TRANSPORT_METADATA:
            value = raw_metadata.get(key)
            if type(value) is int:
                metadata[key] = value
            elif isinstance(value, str):
                metadata[key] = _safe_header(value, 200)
    return code, retryable, status, metadata


def _retry_delay_seconds(code, metadata, now_microseconds):
    if type(metadata.get("retry_after_seconds")) is int:
        return max(1, min(metadata["retry_after_seconds"], 86400))
    if type(metadata.get("rate_limit_reset")) is int:
        wait = metadata["rate_limit_reset"] - now_microseconds // 1_000_000
        return max(1, min(wait, 86400))
    return 60 if code == "RATE_LIMITED" else 2


def _comment_body(task, request, review, result, hub_pointer):
    marker = f"<!-- grokbuddy-final-review:{review['id']} -->"
    body = "\n".join([
        marker,
        "GrokBuddy Final Review",
        f"status={request['status']}",
        f"verdict={review['effective_verdict']}",
        f"summary={_bounded_text(result.get('summary'))}",
        f"task_id={task['id']}",
        f"review_id={review['id']}",
        f"review_request_id={request['id']}",
        f"hub_pointer={hub_pointer}",
    ])
    if len(body.encode("utf-8")) > 4096:
        raise HubError("Projected GitHub Comment exceeds the local control-message limit")
    return marker, body


class GitHubBindingService(Services):
    def bind_pull_request(self, *, repository_id, repository_full_name, pull_request_number,
                          task_id, builder_actor_id="builder", reviewer_actor_id="mock-reviewer",
                          hub_pointer_base="hub://local"):
        if type(repository_id) is not int or repository_id < 1:
            raise HubError("repository_id must be a positive integer")
        if type(pull_request_number) is not int or pull_request_number < 1:
            raise HubError("pull_request_number must be a positive integer")
        if (not isinstance(repository_full_name, str) or "/" not in repository_full_name
                or any(character.isspace() for character in repository_full_name)
                or len(repository_full_name) > 200):
            raise HubError("repository_full_name is invalid")
        if (not isinstance(hub_pointer_base, str) or not hub_pointer_base
                or len(hub_pointer_base) > 500 or "\r" in hub_pointer_base or "\n" in hub_pointer_base):
            raise HubError("hub_pointer_base is required")
        identity = "GHB-" + digest([repository_id, pull_request_number, task_id])
        with self.db.transaction() as repo:
            task = repo.get("tasks", task_id)
            builder = self.actor(repo, builder_actor_id, Role.BUILDER)
            reviewer = self.actor(repo, reviewer_actor_id, Role.REVIEWER)
            if task["owner_id"] != builder["id"]:
                raise HubError("GitHub binding Builder does not own the Task")
            if builder["provider_id"] == reviewer["provider_id"]:
                raise HubError("GitHub binding requires independent Builder and Reviewer identities")
            record = {
                "id": identity,
                "repository_id": repository_id,
                "repository_full_name": repository_full_name,
                "pull_request_number": pull_request_number,
                "task_id": task_id,
                "builder_actor_id": builder_actor_id,
                "reviewer_actor_id": reviewer_actor_id,
                "hub_pointer_base": hub_pointer_base.rstrip("/"),
                "created_at": self.clock.now(),
            }
            old = repo.find("github_bindings", id=identity)
            if old:
                stable = {k: v for k, v in old[0].items() if k != "created_at"}
                desired = {k: v for k, v in record.items() if k != "created_at"}
                if stable != desired:
                    raise Conflict("GitHub binding identity conflicts with existing metadata")
                return old[0]
            if repo.find("github_bindings", task_id=task_id):
                raise Conflict("Task already has a GitHub pull request binding")
            if repo.find("github_bindings", repository_id=repository_id,
                         pull_request_number=pull_request_number):
                raise Conflict("GitHub pull request is already bound to another Task")
            repo.add("github_bindings", record)
            audit(repo, self.clock, self.actor(repo, "system", Role.SYSTEM),
                  "GITHUB_BINDING_CREATED", task_id, repository_id=repository_id,
                  pull_request_number=pull_request_number)
            return record


class GitHubEventService(Services):
    """Durable adapter-level delivery inbox followed by one bounded Hub command."""

    def __init__(self, *args, review_service):
        super().__init__(*args)
        self.review_service = review_service

    def record_rejection(self, *, delivery_id, event_name, raw_sha256, code):
        with self.db.transaction() as repo:
            audit(repo, self.clock, self.actor(repo, "system", Role.SYSTEM),
                  "GITHUB_WEBHOOK_REJECTED", delivery_id=_safe_header(delivery_id, 200),
                  event_name=_safe_header(event_name, 80),
                  raw_sha256=raw_sha256, code=code)

    def ingest(self, *, delivery_id, event_name, raw_sha256, event):
        if not isinstance(event, dict) or event.get("event_name") != event_name:
            raise HubError("Normalized GitHub event does not match its header")
        mapped = event_name == FINAL_TRIGGER_EVENT and event.get("action") == FINAL_TRIGGER_ACTION
        if type(event.get("advances_final_review")) is not bool or event["advances_final_review"] != mapped:
            raise HubError("Normalized GitHub event violates the configured event mapping")
        if mapped and (type(event.get("pull_request_number")) is not int
                       or event["pull_request_number"] < 1):
            raise HubError("Final Review trigger requires a pull request number")
        conflict = False
        with self.db.transaction() as repo:
            previous = repo.find("github_events", delivery_id=delivery_id)
            if previous:
                row = previous[0]
                if row["raw_sha256"] != raw_sha256 or row["event_name"] != event_name:
                    audit(repo, self.clock, self.actor(repo, "system", Role.SYSTEM),
                          "GITHUB_DELIVERY_CONFLICT", raw_sha256=raw_sha256,
                          delivery_id=delivery_id, event_name=event_name)
                    conflict = True
                else:
                    audit(repo, self.clock, self.actor(repo, "system", Role.SYSTEM),
                          "GITHUB_DELIVERY_DUPLICATE", row.get("task_id"),
                          delivery_id=delivery_id, ingress_id=row["id"], status=row["status"])
            else:
                row = {
                    "id": uid("GHE"),
                    "delivery_id": delivery_id,
                    "event_name": event_name,
                    "action": event["action"],
                    "repository_id": event["repository_id"],
                    "repository_full_name": event["repository_full_name"],
                    "resource_type": event["resource_type"],
                    "resource_id": event["resource_id"],
                    "resource_revision": event["resource_revision"],
                    "pull_request_number": event.get("pull_request_number"),
                    "sender_id": event.get("sender_id"),
                    "canonical_key": event["canonical_key"],
                    "advances_final_review": event["advances_final_review"],
                    "raw_sha256": raw_sha256,
                    "received_at": self.clock.now(),
                    "status": "READY",
                }
                repo.add("github_events", row)
                audit(repo, self.clock, self.actor(repo, "system", Role.SYSTEM),
                      "GITHUB_EVENT_RECEIVED", delivery_id=delivery_id, ingress_id=row["id"],
                      event_name=event_name, github_action=event["action"], raw_sha256=raw_sha256)
        if conflict:
            raise Conflict("GitHub delivery ID was reused with different content")
        return self.process(row["id"], duplicate=bool(previous))

    def process(self, ingress_id, duplicate=False):
        with self.db.transaction() as repo:
            row = repo.get("github_events", ingress_id)
            if row["status"] in ("APPLIED", "IGNORED", "UNMAPPED", "DUPLICATE_SEMANTIC", "REJECTED"):
                return self._receipt(row, duplicate=True)
            if not row["advances_final_review"]:
                row["status"] = "IGNORED"
                repo.save("github_events", row)
                audit(repo, self.clock, self.actor(repo, "system", Role.SYSTEM),
                      "GITHUB_EVENT_IGNORED", event_id=row["id"], event_name=row["event_name"],
                      github_action=row["action"], delivery_id=row["delivery_id"])
                return self._receipt(row, duplicate=duplicate)
            semantic = [candidate for candidate in repo.find(
                "github_events", canonical_key=row["canonical_key"]
            ) if candidate["id"] != row["id"] and candidate["status"] in ("APPLIED", "DUPLICATE_SEMANTIC")]
            if semantic:
                original = semantic[0]
                row.update(status="DUPLICATE_SEMANTIC", task_id=original.get("task_id"),
                           review_request_id=original.get("review_request_id"),
                           effect_status=original.get("effect_status"))
                repo.save("github_events", row)
                audit(repo, self.clock, self.actor(repo, "system", Role.SYSTEM),
                      "GITHUB_SEMANTIC_DUPLICATE", row.get("task_id"), event_id=row["id"],
                      delivery_id=row["delivery_id"], original_ingress_id=original["id"])
                return self._receipt(row, duplicate=True)
            bindings = repo.find("github_bindings", repository_id=row["repository_id"],
                                 pull_request_number=row["pull_request_number"])
            if not bindings:
                row["status"] = "UNMAPPED"
                repo.save("github_events", row)
                audit(repo, self.clock, self.actor(repo, "system", Role.SYSTEM),
                      "GITHUB_EVENT_UNMAPPED", event_id=row["id"], repository_id=row["repository_id"],
                      pull_request_number=row["pull_request_number"])
                return self._receipt(row, duplicate=duplicate)
            binding = bindings[0]
            if row["status"] == "READY":
                task = repo.get("tasks", binding["task_id"])
                future_routes = repo.find("grok_reviewer_routes", task_id=task["id"])
                reviewer_actor_id = (future_routes[0]["reviewer_actor_id"] if future_routes
                                     else binding["reviewer_actor_id"])
                row.update(status="PREPARED", binding_id=binding["id"], task_id=task["id"],
                           builder_actor_id=binding["builder_actor_id"],
                           reviewer_actor_id=reviewer_actor_id,
                           requested_version=task["version"],
                           command_key="phase3:github:" + digest(row["canonical_key"]))
                repo.save("github_events", row)

        try:
            response = self.review_service.request_review(
                row["builder_actor_id"], row["task_id"], "FINAL_REVIEW",
                row["reviewer_actor_id"], row["requested_version"], row["command_key"])
        except HubError as exc:
            with self.db.transaction() as repo:
                current = repo.get("github_events", ingress_id)
                if current["status"] == "PREPARED":
                    current.update(status="REJECTED", error_code=exc.code)
                    repo.save("github_events", current)
                    audit(repo, self.clock, self.actor(repo, "system", Role.SYSTEM),
                          "GITHUB_EVENT_REJECTED", current.get("task_id"), event_id=current["id"],
                          delivery_id=current["delivery_id"], code=exc.code)
            raise
        if response.get("status") != "PENDING" or not response.get("review_request_id"):
            raise HubError("Final review request did not return a PENDING receipt")
        with self.db.transaction() as repo:
            current = repo.get("github_events", ingress_id)
            current.update(status="APPLIED", review_request_id=response["review_request_id"],
                           effect_status=response["status"], applied_at=self.clock.now())
            repo.save("github_events", current)
            audit(repo, self.clock, self.actor(repo, "system", Role.SYSTEM),
                  "GITHUB_EVENT_APPLIED", current["task_id"], event_id=current["id"],
                  request_id=response["review_request_id"], delivery_id=current["delivery_id"])
            return self._receipt(current, duplicate=duplicate)

    @staticmethod
    def _receipt(row, duplicate=False):
        receipt = {
            "ingress_id": row["id"],
            "delivery_id": row["delivery_id"],
            "event": row["event_name"],
            "action": row["action"],
            "status": row["status"],
            "duplicate": duplicate,
        }
        if row.get("review_request_id"):
            receipt["effect"] = {
                "review_request_id": row["review_request_id"],
                "status": row.get("effect_status", "PENDING"),
            }
        if row.get("error_code"):
            receipt["error_code"] = row["error_code"]
        return receipt


class GitHubProjectionService(Services):
    def enqueue_final_review(self, review_request_id):
        with self.db.transaction() as repo:
            request = repo.get("review_requests", review_request_id)
            if request["review_type"] != "FINAL_REVIEW" or request["status"] != "COMPLETED":
                raise HubError("Only a completed Final Review can be projected")
            reviews = repo.find("reviews", review_request_id=review_request_id)
            if len(reviews) != 1:
                raise HubError("Completed Final Review snapshot is missing")
            review = reviews[0]
            task = repo.get("tasks", request["task_id"])
            bindings = repo.find("github_bindings", task_id=task["id"])
            if len(bindings) != 1:
                raise HubError("Task has no unique GitHub pull request binding")
            binding = bindings[0]
            _, content = self.artifact(repo, task["id"], review["result_artifact_id"], review["result_hash"])
            try:
                result = json.loads(content)
            except (UnicodeError, ValueError) as exc:
                raise HubError("Stored Review result artifact is invalid") from exc
            hub_pointer = (f"{binding['hub_pointer_base']}/tasks/{task['id']}"
                           f"/reviews/{review['id']}")
            marker, body = _comment_body(task, request, review, result, hub_pointer)
            desired_hash = digest(body)
            identity = "GHP-" + digest([review["id"], binding["id"]])
            # Step 6.3 may have atomically created an UNKNOWN intent before a
            # GitHub binding existed.  Upgrade that row instead of creating a
            # second business intent for the same immutable Review.
            old = repo.find("github_comment_projections", review_id=review["id"])
            if old:
                row = old[0]
                if row.get("binding_id") != binding["id"] or row.get("desired_hash") != desired_hash:
                    row.update(binding_id=binding["id"], marker=marker,
                               desired_hash=desired_hash, desired_body=body, status="READY",
                               lease_token=None, lease_until=0, next_attempt_at=self.clock.now(),
                               frozen_review_hash=review["result_hash"],
                               frozen_task_version=task["version"], recovery_reason=None)
                    repo.save("github_comment_projections", row)
                return row
            row = {
                "id": identity,
                "task_id": task["id"],
                "review_request_id": request["id"],
                "review_id": review["id"],
                "binding_id": binding["id"],
                "marker": marker,
                "desired_body": body,
                "desired_hash": desired_hash,
                "applied_hash": None,
                "comment_id": None,
                "comment_url": None,
                "status": "READY",
                "attempts": 0,
                "next_attempt_at": self.clock.now(),
                "lease_until": 0,
                "lease_token": None,
                "lease_generation": 0,
                "intent_kind": "FINAL_REVIEW_COMMENT",
                "frozen_review_hash": review["result_hash"],
                "frozen_task_version": task["version"],
                "created_at": self.clock.now(),
            }
            repo.add("github_comment_projections", row)
            audit(repo, self.clock, self.actor(repo, "system", Role.SYSTEM),
                  "GITHUB_COMMENT_PROJECTION_QUEUED", task["id"], request_id=request["id"],
                  review_id=review["id"], desired_hash=desired_hash)
            return row

    def _claim(self):
        with self.db.transaction() as repo:
            for row in repo.find("github_comment_projections"):
                if not row.get("binding_id") or not row.get("desired_body"):
                    continue
                ready = row["status"] in ("READY", "RETRY", "UNKNOWN") and row["next_attempt_at"] <= self.clock.now()
                expired = row["status"] == "LEASED" and row["lease_until"] <= self.clock.now()
                if not (ready or expired):
                    continue
                claimed_from_status = "UNKNOWN" if expired else row["status"]
                row.update(status="LEASED", lease_token=uid("LEASE"),
                           lease_generation=row.get("lease_generation", 0) + 1,
                           lease_until=self.clock.now() + self.settings.lease_seconds * 1_000_000,
                           attempts=row["attempts"] + 1,
                           claimed_from_status=claimed_from_status)
                repo.save("github_comment_projections", row)
                return row
        return None

    def project_one(self, transport):
        row = self._claim()
        if row is None:
            return None
        with self.db.transaction() as repo:
            binding = repo.get("github_bindings", row["binding_id"])
        phase = "find"
        try:
            existing = transport.find_comment(binding, row["marker"])
            if existing:
                if existing.get("body") != row["desired_body"]:
                    phase = "update"
                    comment = transport.update_comment(binding, str(existing["id"]), row["desired_body"])
                    operation = "UPDATED"
                else:
                    comment = existing
                    operation = "UNCHANGED"
            else:
                if row.get("claimed_from_status") == "UNKNOWN":
                    with self.db.transaction() as repo:
                        current = repo.get("github_comment_projections", row["id"])
                        if (current["status"] != "LEASED" or current["lease_token"] != row["lease_token"]
                                or current.get("lease_generation", 0) != row["lease_generation"]):
                            return "LEASE_LOST"
                        exhausted = current["attempts"] >= self.settings.delivery_max_attempts
                        outcome = "FAILED" if exhausted else "UNKNOWN"
                        current.update(status=outcome, lease_token=None,
                                       next_attempt_at=self.clock.now() + 2_000_000,
                                       reconciliation_checks=current.get("reconciliation_checks", 0) + 1,
                                       last_safe_error="COMMENT_CREATE_UNCONFIRMED")
                        repo.save("github_comment_projections", current)
                        audit(repo, self.clock, self.actor(repo, "system", Role.SYSTEM),
                              "GITHUB_COMMENT_RECONCILE_" + outcome, current["task_id"],
                              request_id=current["review_request_id"], review_id=current["review_id"],
                              attempt=current["attempts"])
                    return outcome
                phase = "create"
                comment = transport.create_comment(binding, row["desired_body"])
                operation = "CREATED"
            if not isinstance(comment, dict) or not comment.get("id"):
                raise HubError("GitHub Comment transport returned an invalid receipt")
        except Exception as exc:
            error_code, retryable, http_status, safe_metadata = _transport_failure(exc)
            outcome = "LEASE_LOST"
            with self.db.transaction() as repo:
                current = repo.get("github_comment_projections", row["id"])
                if (current["status"] == "LEASED" and current["lease_token"] == row["lease_token"]
                        and current.get("lease_generation", 0) == row["lease_generation"]):
                    ambiguous_create = phase == "create" and retryable
                    reconcile_failure = (row.get("claimed_from_status") == "UNKNOWN"
                                         and phase == "find" and retryable)
                    terminal = (not retryable or (
                        current["attempts"] >= self.settings.delivery_max_attempts
                        and not ambiguous_create and not reconcile_failure))
                    outcome = ("FAILED" if terminal else "UNKNOWN"
                               if ambiguous_create or reconcile_failure else "RETRY")
                    delay = _retry_delay_seconds(error_code, safe_metadata, self.clock.now())
                    current.update(status=outcome, lease_token=None,
                                   next_attempt_at=self.clock.now() + delay * 1_000_000,
                                   last_safe_error=error_code,
                                   last_http_status=http_status,
                                   last_error_retryable=retryable,
                                   last_error_metadata=safe_metadata)
                    repo.save("github_comment_projections", current)
                    audit(repo, self.clock, self.actor(repo, "system", Role.SYSTEM),
                          "GITHUB_COMMENT_PROJECTION_FAILED", current["task_id"],
                          request_id=current["review_request_id"], review_id=current["review_id"],
                          terminal=terminal, error_code=error_code, retryable=retryable,
                          http_status=http_status, safe_metadata=safe_metadata)
            return outcome
        with self.db.transaction() as repo:
            current = repo.get("github_comment_projections", row["id"])
            if (current["status"] != "LEASED" or current["lease_token"] != row["lease_token"]
                    or current.get("lease_generation", 0) != row["lease_generation"]):
                return "LEASE_LOST"
            current.update(status="SENT", lease_token=None, applied_hash=current["desired_hash"],
                           comment_id=str(comment["id"]), comment_url=comment.get("url"),
                           projected_at=self.clock.now(), last_safe_error=None,
                           last_http_status=None, last_error_retryable=None,
                           last_error_metadata={})
            repo.save("github_comment_projections", current)
            audit(repo, self.clock, self.actor(repo, "system", Role.SYSTEM),
                  "GITHUB_COMMENT_" + operation, current["task_id"],
                  request_id=current["review_request_id"], review_id=current["review_id"],
                  comment_id=current["comment_id"], desired_hash=current["desired_hash"])
        return operation
