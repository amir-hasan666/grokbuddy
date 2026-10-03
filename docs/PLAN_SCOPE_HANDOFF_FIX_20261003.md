# Plan scope handoff repair — 2026-10-03

Status: **LOCAL FIX COMPLETE; FULL LOCAL REGRESSION PASS; NOT DEPLOYED**.

Human authorized repository maintenance only: scope semantics, frozen scope/hash material, preparation diagnostics and regression coverage. No business Task mutation, production deployment/restart, credential change or external Reviewer call is authorized by this record.

## Problem and resulting behavior

The incident report for `TASK-fc069b71-7dc1-4da1-9558-2ce70da1bebc` treated the missing repository-selection evidence Finding as a rule that `approved_scope.files` must equal submitted Plan materials. Its Plan §9.4 encoded that incorrect rule, leaving only PLAN.md in the allowlist while the original requirement and Plan described a later app. Plan PASS preserved that scope, so the existing Final subset guard correctly rejected app files.

The repair separates the whole-Task change allowlist from current-review supporting materials. Future files may be declared before creation; Plan PASS remains required before coding. Document-only deliverables remain valid when they match the actual requirement. This patch does not repair or rewrite the incident Task or its frozen Plan.

## Implementation

- [Plan scope contract](contracts/PLAN_SCOPE_CONTRACT.md), shared schema definitions, MCP field/tool descriptions, examples, WorkBuddy integration and the repository Plan-remediation Skill now state one meaning for scope.
- New v2 Plan RRs freeze `context.plan_scope={schema_version:1,scope,sha256}` in the existing immutable context Artifact. Request creation validates the schema and the canonical scope hash. Existing authenticated material access supplies the bytes; later Task revisions cannot replace old RR content.
- [Readiness query](../src/grokbuddy/application/tasks.py) accepts optional `planned_changed_files` from the Plan's whole-Task output manifest. It reports missing scope/files, nonexact paths, hash mismatch and uncovered planned files. It does not persist this input, expand scope or consume a round.
- Omitted input remains compatible and reports coverage `NOT_CHECKED`. The check compares explicit paths; it does not infer intent from Markdown, profile or filename extension. WorkBuddy must derive the manifest independently, and Reviewer must compare it with the original requirement and Plan.
- Existing Final subset checks, scope approval, two-round caps, identities, asynchronous APPLY and historical Review/Task behavior are retained. The added preparation result is a hint, not a replacement approval or new blanket prohibition against legitimate R2 BLOCK.

## Version and compatibility

New frozen snapshot and readiness diagnostics use `schema_version=1`. Definitions are additive under the existing common schema; request/result v1/v2 envelopes and the V1 decision policy are unchanged. The bundle still contains four root schemas. Unknown snapshot versions must not be treated as version1. Historical contexts without this field remain without it; no reconstruction from current Task state, migration or backfill occurs.

## Local validation

- Targeted tests: `tests/test_plan_scope_handoff.py`, `tests/test_plan_finding_remediation.py`, `tests/test_review_handoff.py`, `tests/test_v1_dual_round_decisions.py`, `tests/test_phase6_ingress_builder_drive.py`: **75 passed**.
- [Document/contract checks](plan-scope-contract-checks-20261003.json): **283/283 passed**, including the positive scope snapshot, required/unknown-field and negative version/scope mutations, links and canonical example hash. The existing checker functions were used without overwriting historical phase0/phase1 reports.
- Full local regression: `.venv/Scripts/python.exe -m pytest -q`: **942 passed** in 258.65 seconds. This includes existing Final out-of-scope rejection and V1 Plan/Final two-round guards.
- Git diff reviewed and `git diff --check` passed. No unrelated source/configuration or historical report edits were included.

The new tests use disposable storage and controlled local reviewers only. They prove their local assertions, not formal production or external GrokBot acceptance.

## Rule synchronization and later release

1. Review the final patch and validation record. Under separate Human authorization, use the existing formal release/rollback procedure: record runtime configuration and loaded revision, preserve a non-secret rollback package, retain the configured runtime, and perform a controlled service restart. No database migration is required by this patch. Do not add a business Task or submit a review as a deployment smoke test.
2. Ensure WorkBuddy's Hub MCP process and tool-schema cache reload the changed source; verify `get_plan_review_readiness.planned_changed_files` and the whole-Task files description are visible. Sync the updated repository [Plan-remediation Skill](workbuddy-skills/grokbuddy-plan-remediation/SKILL.md) using the [WorkBuddy prompt](WORKBUDDY_REVIEW_HANDOFF_PROMPT.md). No installed external Skill was changed by this maintenance.
3. Use the [GrokBot prompt](GROKBOT_REVIEW_HANDOFF_PROMPT.md) to update the external persistent review rules. After release, authenticated GET of the schema bundle should expose `common.$defs.plan_scope_snapshot_v1`; successful schema retrieval does not prove substantive review behavior.
4. Only in a separately authorized real business run, read the new RR context, verify its Artifact and scope hashes, and compare the original demand/Plan/file allowlist. Observe actual Reviewer result and Hub APPLY. This is the remaining production acceptance evidence; local fixture PASS does not establish it.
5. Treat recovery of the incident Task separately. The patch neither extends its approved scope nor resets its Plan budget. A replacement business Task requires explicit Human authorization and fresh task-scoped materials/review; preserve all old findings and results.

Current production remains the baseline described by [Current Production Baseline](CURRENT_PRODUCTION_BASELINE.md). This local record does not close V1 6.21/6.22 or alter historical Phase reports.
