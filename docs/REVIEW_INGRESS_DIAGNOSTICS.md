# Reviewer ingress rejection diagnostics

This document describes the additive local implementation introduced on 2026-10-02. Deployment and external Reviewer verification are separate. Review result schemas, verdict rules, deadlines, identity checks and the frozen V1 two-round limit are unchanged.

## Asynchronous response and safe snapshot

`POST /reviewer/events` still returns `202` with `ingress_id` and `status=READY` after durable intake. The authenticated Reviewer queries `GET /reviewer/ingress/<IN>` for the later business outcome. The existing RR/Task/Reviewer scope checks also protect all diagnostic fields.

At APPLY rejection, the inbox receipt stores a safe snapshot built from validated Task-scoped records. The rejected business transaction rolls back; only the receipt and rejection Audit commit. No raw exception, result summary, Finding title/description, evidence text or credential is copied into diagnostics. Audit adds only the controlled reason code and field path.

The GET response preserves `status`, `error_code`, `field_path` and `field_path_source`, and adds:

| Field | Meaning |
| --- | --- |
| `reason_code` | Controlled business rejection reason, or null when no stored reason exists. |
| `rejection_details` | Stored safe metadata, or null. |
| `rejection_details_source` | `STORED` for persisted rejection-time metadata; otherwise null. |

`rejection_details` contains `reason_code`, `field_path`, `unresolved_findings` (ID, validation-time status, severity) and `blocking_open_findings` (IDs of non-advisory OPEN items that prevent PASS). FIXED and REJECTED_WITH_EVIDENCE can also prevent PASS, so clients must inspect `unresolved_findings` rather than treating an empty OPEN list as approval.

## Reasons

| `error_code` | `reason_code` | Details |
| --- | --- | --- |
| `ILLEGAL_TRANSITION` | `FINDING_NOT_READY_FOR_VERIFICATION` | `invalid_finding_transitions[]` lists all checked invalid verification operations: Finding ID, current status, requested outcome, allowed statuses and `$.verifications[index].finding_id`. |
| `VALIDATION_FAILURE` | `PASS_HAS_UNRESOLVED_FINDINGS` | `$.verdict` identifies a PASS with remaining actionable Findings after otherwise valid projected verification operations. |

Finding transition eligibility still comes from the Domain rules. A verification cannot bypass Builder accept/fix. Invalid scope, changed frozen Finding version, unreadable evidence or other earlier guards remain rejected with their original error code; they do not disclose unvalidated or cross-Task Finding metadata.

## Historical receipts

Queries do not update receipts or rerun business APPLY. Stored details remain the original snapshot after later Finding changes, timeout or restart. Historical receipts without these fields return null reason/details/source. Existing safe `CURRENT_SCHEMA_REVALIDATION` behavior for a missing schema field path remains explicitly labelled and is not a reconstruction of historical business rejection reasons.
