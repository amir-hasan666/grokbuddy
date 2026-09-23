# Current Production Baseline

Last updated: 2026-09-22 18:44 Asia/Shanghai

This file is a mutable pointer to the current production baseline.
It is not historical evidence and must not rewrite or supersede the
recorded facts in dated Phase reports.

## Current stage

- Phase 6 is in progress.
- [Phase 6 Step 6.20 Real Final E2E](PHASE6_STEP6_20_REAL_FINAL_E2E_REPORT.md) is `PHASE6-STEP6.20-REAL-FINAL-E2E: PASS` for the core Hub business path. Its GitHub projection is honestly `UNKNOWN` and is non-blocking for the Hub verdict.
- This does not declare all of Phase 6 complete. Phase 6.21/6.22 remain open unless and until their own authorized work and evidence reports close them.

## Closed gates

Only the linked dated reports establish these results:

- [Phase 6 Step 6.17 Trigger Isolation](PHASE6_STEP6_17_TRIGGER_ISOLATION_REPORT.md): first line `PHASE6-STEP6.17-TRIGGER-ISOLATION: PASS`.
- [Phase 6 Step 6.19 RuntimeDir Source of Truth Alignment](PHASE6_STEP6_19_RUNTIME_SOT_ALIGN_NOTE.md): first line `PHASE6-STEP6.19: PASS`.
- [Phase 6 Step 6.20 Real Final E2E](PHASE6_STEP6_20_REAL_FINAL_E2E_REPORT.md): first line `PHASE6-STEP6.20-REAL-FINAL-E2E: PASS`.

These closed gates establish only their linked scopes. In particular, 6.20 does not establish GitHub projection success or the exit of all Phase 6 work.

## Deployment facts

The formal runtime configuration is [config/grokbuddy.service.json](../config/grokbuddy.service.json). At this update it specifies:

| Field | Current configured value |
| --- | --- |
| `runtimeDir` | `var/github-manual` |
| `contractsDir` | `docs/contracts` |
| `host` | `127.0.0.1` |
| `port` | `8788` |
| `publicBase` | `https://grokbuddy.amirhasan.top` |
| `reviewerActor` | `grok-reviewer-b` |
| `supervisorEnabled` | `true` |
| `supervisorIntervalSeconds` | `5` |
| `githubCommentTokenEnv` | `GITHUB_COMMENT_TOKEN` |

The JSON file remains the runtime configuration authority for these values. This baseline explains their current operational role; it does not replace the config.

## Formal production entry topology

The current formal production topology is:

1. `grokbuddy-ingress` is the dedicated WorkBuddy trigger surface. It exposes only `create_triggered_task` and enters the original Application/Domain guard with the fixed ingress principal.
2. `grokbuddy-hub` is the Builder/Human stdio surface for the same configured Hub runtime. It drives governed Plan, Review, Finding, Artifact and Human Gate use cases; it is not the trigger-signing surface.
3. `grokbuddy-worker` is the assignment-based Worker surface for the same configured Hub runtime. It does not create or own trigger intake.
4. The Windows Hub production launcher reads `config/grokbuddy.service.json`, starts the composite HTTP service and the enabled long-running supervisor. Reviewer delivery uses the configured production Reviewer actor and the delivery channel frozen for each Review Request.
5. Hub persistence remains the business Source of Truth. Reviewer and GitHub surfaces are authenticated input, transport, or projection; they cannot independently establish a Hub verdict or Task state.

Operational commands and credential-safe checks are maintained in the [Windows Operations Runbook](PHASE6_OPERATIONS_RUNBOOK.md). MCP configuration and role details are maintained in [WorkBuddy Integration](WORKBUDDY_INTEGRATION.md). A future topology change must update this file instead of freezing the new topology into root `AGENTS.md` or `README.md`.

## Paths that cannot establish production evidence

The following may remain useful for development or diagnosis but cannot substitute for the formal production path:

- direct Gateway or `LocalRuntime` calls;
- mock reviewers, mock transports, fixtures or temporary drivers;
- `run_until_idle`, `*_once`, manual event/dispatch/projection commands or temporary resume scripts;
- manual database changes, owner rewrites, copied findings/results or fabricated bindings/routes;
- historical Quick Tunnel, legacy port/runtime examples, or a local test run presented as current deployment evidence.

Formal Phase 6.20 evidence requires Manual Glue = 0 as defined by the frozen [Manual Glue / Supervisor Contract](PHASE6_STEP6_0A_MANUAL_GLUE_SUPERVISOR_CONTRACT.md).

## Normative and operational precedence

When sources appear to conflict, use this order:

1. Frozen current production contract and `docs/contracts/`.
2. `config/grokbuddy.service.json` and other formal runtime configuration.
3. `docs/CURRENT_PRODUCTION_BASELINE.md` as the current Gate/deployment-fact pointer.
4. Current implementation code, which must conform to the preceding contract and configuration; conflict is an **implementation defect**.
5. Dated Phase reports as historical/locked evidence.
6. Root `AGENTS.md` and `README.md` as long-term rules and navigation; they do not maintain phase status.
7. Legacy and older-phase material.

> 代码与现行 contract 冲突时，不得以「代码是当前实现」为由修改 contract 迁就代码；应报告 implementation/contract drift。

## Current Phase 6.20 status and evidence pointer

The dated [Phase 6 Step 6.20 Real Final E2E Report](PHASE6_STEP6_20_REAL_FINAL_E2E_REPORT.md) is the evidence authority for this Gate. This mutable pointer summarizes, but does not recreate, that evidence:

- Core PASS scope: Task `TASK-702a9f15-b1a7-4a2c-a5ef-0c1a12d2a5bd` remained owned by `workbuddy-ingress` and reached `DONE`, version `15`, content revision `2`, with `completion_basis=FINAL_REVIEW_PASS`; the approved Plan, assignment-based Worker execution, self-test, frozen Final package and Reviewer B Final PASS remained on the same Task.
- Production path: WorkBuddy used only the `grokbuddy-ingress`, `grokbuddy-hub` and `grokbuddy-worker` MCP surfaces against `var/github-manual`; the configured long-running Supervisor supplied Hub background work; the successful path had Manual Glue = 0.
- Immutable early failures remain evidence: `RR-bebe1782-4a1d-4885-9b1c-9443b1f87a60` and `RR-32116386-3daa-4ced-a9e3-da87876cd3eb` remain `TIMED_OUT / REVIEW_TIMEOUT`. They were not rewritten or revived when later Review Requests succeeded.
- Successful Plan: `RR-cfb06e90-0966-4631-97f7-f81bf5ebe37d`, Plan round 3, `REVIEWER_HTTP`, Reviewer `grok-reviewer-b`, `COMPLETED / PASS`, followed by Hub APPLY and `PLAN_APPROVED`.
- Successful Final: `RR-7ec054b2-679f-4948-8882-ca1a0cedd016`, Final round 1, `REVIEWER_HTTP`, Reviewer `grok-reviewer-b`, `COMPLETED / PASS`, followed by Hub APPLY and `DONE / FINAL_REVIEW_PASS`.
- Honest projection boundary: `GHP-50d8c21ef46f3137283daf95ce8714a7c9c3dbaa471b7674b03b4292ba9df716` is `UNKNOWN` with `binding_id=null`. It is not projection PASS. Under the frozen contract, projection failure or absence does not roll back the authoritative Hub Review or Task terminal state.

The earlier [MCP submit-plan scope report](PHASE6_MCP_SUBMIT_PLAN_SCOPE_FIX_REPORT.md), [Supervisor production wiring report](PHASE6_SUPERVISOR_PRODUCTION_WIRING_REPORT.md), and [Reviewer Delivery Gap Report](PHASE6_REVIEWER_DELIVERY_GAP_REPORT.md) retain their point-in-time `LOCAL PASS / WAITING ...` conclusions as historical evidence. This baseline does not rewrite those reports; the later 6.20 report records the subsequently completed production path.

Optional follow-up work, separate from the 6.20 core PASS:

- add a verified webhook-based automatic wake for Reviewer intake while preserving controlled polling, durable ACK and deduplication semantics;
- improve the operations documentation for lease/fencing and uncertain-receipt reconciliation;
- leave the no-binding GitHub projection `UNKNOWN` unless a real binding is produced through the governed workflow.

The [Control Plane Detemporalize Report](PHASE6_CONTROL_PLANE_DETEMPORALIZE_REPORT.md) remains `PHASE6-CONTROL-PLANE-DETEMPORALIZE: LOCAL PASS / DOCS ONLY`. It explains the mutable-baseline design and is separate from the 6.20 production E2E evidence.
