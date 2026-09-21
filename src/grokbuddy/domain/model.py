from dataclasses import dataclass
from enum import StrEnum


class HubError(Exception):
    code = "VALIDATION_FAILURE"


class Conflict(HubError):
    code = "CONFLICT"


class TriggerEvidenceRequired(HubError):
    code = "TRIGGER_EVIDENCE_REQUIRED"


class TriggerEvidenceInvalid(HubError):
    code = "TRIGGER_EVIDENCE_INVALID"


class TriggerNotFound(HubError):
    code = "TRIGGER_NOT_FOUND"


class TriggerSourceUnavailable(HubError):
    code = "TRIGGER_SOURCE_UNAVAILABLE"


class ActiveConversationTask(Conflict):
    code = "ACTIVE_CONVERSATION_TASK"


class PermissionDenied(HubError):
    code = "PERMISSION_FAILURE"


class NotFound(HubError):
    code = "NOT_FOUND"


class IllegalTransition(HubError):
    code = "ILLEGAL_TRANSITION"


class RetryableDelivery(HubError):
    code = "RETRYABLE"


class DeliveryUnknown(HubError):
    code = "DELIVERY_UNKNOWN"


class Role(StrEnum):
    BUILDER = "BUILDER"
    REVIEWER = "REVIEWER"
    HUMAN = "HUMAN"
    SYSTEM = "SYSTEM"


class TaskState(StrEnum):
    NEW = "NEW"
    PLANNING = "PLANNING"
    PLAN_REVIEW_PENDING = "PLAN_REVIEW_PENDING"
    PLAN_REVIEWING = "PLAN_REVIEWING"
    PLAN_CHANGES_REQUIRED = "PLAN_CHANGES_REQUIRED"
    PLAN_HUMAN_REVIEW = "PLAN_HUMAN_REVIEW"
    PLAN_APPROVED = "PLAN_APPROVED"
    EXECUTING = "EXECUTING"
    SELF_TESTING = "SELF_TESTING"
    FINAL_REVIEW_PENDING = "FINAL_REVIEW_PENDING"
    FINAL_REVIEWING = "FINAL_REVIEWING"
    FINAL_CHANGES_REQUIRED = "FINAL_CHANGES_REQUIRED"
    FINAL_HUMAN_REVIEW = "FINAL_HUMAN_REVIEW"
    AWAITING_HUMAN_APPROVAL = "AWAITING_HUMAN_APPROVAL"
    BLOCKED = "BLOCKED"
    ESCALATED = "ESCALATED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    DONE = "DONE"


class RequestStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    ESCALATED = "ESCALATED"


class FindingStatus(StrEnum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    REJECTED_WITH_EVIDENCE = "REJECTED_WITH_EVIDENCE"
    FIXED = "FIXED"
    VERIFIED = "VERIFIED"
    WAIVED_BY_HUMAN = "WAIVED_BY_HUMAN"


class Verdict(StrEnum):
    PASS = "PASS"
    NEEDS_CHANGES = "NEEDS_CHANGES"
    BLOCK = "BLOCK"


class ReviewType(StrEnum):
    PLAN = "PLAN_REVIEW"
    FINAL = "FINAL_REVIEW"


TERMINAL = {TaskState.DONE, TaskState.CANCELLED, TaskState.FAILED}
ACTIVE_REQUEST = {RequestStatus.PENDING, RequestStatus.IN_PROGRESS}
CLOSED_FINDING = {FindingStatus.VERIFIED, FindingStatus.WAIVED_BY_HUMAN}


@dataclass(frozen=True)
class Settings:
    max_plan_review_rounds: int = 2
    max_final_review_rounds: int = 3
    max_human_plan_extra_rounds: int = 2
    max_human_final_extra_rounds: int = 3
    max_findings_per_review: int = 100
    plan_review_timeout: int = 900
    final_review_timeout: int = 1800
    max_task_duration: int = 86400
    delivery_max_attempts: int = 5
    lease_seconds: int = 30
    max_artifact_bytes: int = 50 * 1024 * 1024

    def __post_init__(self):
        if any(type(v) is not int or v < 1 for v in vars(self).values()):
            raise ValueError("Settings must contain positive integers")


@dataclass(frozen=True)
class NormalizedEvent:
    event_id: str
    event_type: str
    source: str
    actor_id: str  # Supplied by the trusted ingress, never by review JSON.
    task_id: str
    review_request_id: str
    review_id: str
    correlation_id: str
    deduplication_key: str
    payload: dict
    execution_identity: dict | None = None


@dataclass(frozen=True)
class DeliveryReceipt:
    status: str  # ACCEPTED / UNKNOWN / NOT_FOUND; no verdict.
