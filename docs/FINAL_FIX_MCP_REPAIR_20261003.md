# Final-fix client repair — 2026-10-03

Local closeout status before formal release: **LOCAL FIX COMPLETE; FULL LOCAL REGRESSION PASS; NOT DEPLOYED**.

Subsequent authorized [production release](PRODUCTION_SCOPE_FINAL_FIX_RELEASE_20261003.md) loaded commit b9580f4 into the formal Hub at 14:31 on the same date. WorkBuddy MCP reload and real Task remediation remain unverified. The following local validation and implementation record is preserved.

Human authorized this repository repair after WorkBuddy reported a blocked Final R1 remediation on `TASK-84255b22-cd5c-487f-b2be-c8b9dbbbb7bd`. The business report is context, not proof of its current Task state or Final acceptance. This maintenance does not mutate that Task, submit its reviews, deploy/restart services or change credentials.

## Diagnosis and change

The application already implements `begin_final_fix` with Builder authorization, current Task version, v2/FINAL_CHANGES_REQUIRED state, frozen Finding IDs, approved scope and a durable Worker assignment. ClientGateway and the WorkBuddy stdio MCP omitted that command. Meanwhile, the Final `respond_to_review(fix)` adapter automatically called legacy `move(execute)`; v2 correctly rejects that route. Exposing the command alone would leave that second adapter defect in place.

The client repair exposes the existing command through Gateway and stdio MCP and changes v2 Final responses to delegate directly to `respond_finding`, after explicit remediation. Multiple Finding fixes no longer attempt another execute transition. Historical protocol v1 retains its legacy path. FindingService also checks that a v2 Final fix belongs to `active_fix_finding_ids`; without this check a caller could begin a smaller subset and then mark an unrelated Final Finding fixed while EXECUTING. The regression verifies that such a fix fails without changing Task or Finding state.

The new MCP command uses a fixed configured Builder, a nonempty structured scope, unique nonempty Finding IDs, Task CAS and a stable idempotency key. Unknown top-level and nested scope fields fail rather than being silently discarded by the MCP SDK. Same-key replay returns the existing assignment; changed input with that key fails. Remote MCP remains read-only, and the Worker MCP does not receive this control command.

No new persisted or response machine fields, database migration, request/result protocol version, Reviewer policy or round-budget changes are introduced by this client repair. `begin_final_fix` returns the application's existing `EXECUTING/task/assignment` or `PLAN_CHANGE_REQUIRED/task` shape. Tool discovery is the capability check; an older process/tool-schema cache will not expose it until reloaded.

The existing out-of-scope branch is deliberately preserved: it revokes approval and returns to Plan preparation, without increasing the Plan budget. Callers must compare files/components with approved_scope before submitting. This is not a scope-amendment bypass.

## Local validation

- `.venv/Scripts/python.exe -m pytest tests/test_final_fix_mcp.py -q`: **19 passed** in 41.92 seconds after the active-Finding guard was added. These cover three consecutive Finding fixes through MCP, assignment replay and conflicting retries, Worker-before-self-test, independent R2 PASS/BLOCK, strict schemas, role/CAS/deadline checks, frozen and active Finding subsets, and the existing out-of-scope replan branch.
- `.venv/Scripts/python.exe -m pytest -q`: **961 passed** in 343.86 seconds on the final source. The full run includes Gateway/stdio/remote/Worker compatibility, Plan remediation, Final scope rejection and V1 two-round limits, together with the pending Plan-scope patch.
- Existing `validate_phase0.validate_documents(allow_core=True)` and `validate_contracts()` functions: **282/282 passed**. Historical phase0/phase1 output files were not overwritten.
- Updated WorkBuddy Skill YAML/header, unique allowed-tool list and the new capability reference: **PASS** (14 tools).
- Git diff reviewed and `git diff --check` passed. The earlier pending Plan-scope changes were preserved; no production configuration or business records were changed.

All tests use disposable Hub storage and controlled local reviewers. Their PASS is not a production acceptance claim, and no real WorkBuddy/GrokBot remediation on the reported Task was executed by this maintenance.

## Release and business continuation

1. Under separate Human production authorization, use the existing controlled release/rollback procedure for the reviewed working-tree patch, including the pending [Plan scope repair](PLAN_SCOPE_HANDOFF_FIX_20261003.md). Record the loaded revisions/configuration and preserve a rollback package. This record is not deployment authorization.
2. Reload the WorkBuddy Hub MCP process and client tool cache, using the existing configuration and identities. Verify the new tool and strict input schema are visible. Update the installed WorkBuddy rules from the repository [Final review Skill](workbuddy-skills/grokbuddy-final-review-package/SKILL.md) and [rules prompt](WORKBUDDY_REVIEW_HANDOFF_PROMPT.md). This repair edits repository Skill sources only.
3. GrokBot needs no new event/schema for this command. Its existing rule must still distinguish Builder FIXED from Reviewer VERIFIED and return real R2 verifications. The pending Plan-scope rule synchronization remains separate; use the existing [GrokBot prompt](GROKBOT_REVIEW_HANDOFF_PROMPT.md) for that work.
4. Human may then give WorkBuddy the [current Task continuation prompt](WORKBUDDY_FINAL_FIX_RESUME_PROMPT.md). Read current Hub state/version first; do not hardcode the reported v10. Accept outstanding OPEN findings, start the bounded fix, complete its new Worker assignment, provide actual fix evidence, rebuild/self-test the Final materials and request only the permitted R2 with begin_execution=false.
5. Observe actual Reviewer result, Finding verification and Hub APPLY. R2 may PASS or BLOCK; neither uploaded files, Worker completion, preflight ready nor FIXED implies acceptance. Do not increase budgets, replace reviews or change the business Task through maintenance tools.

Real Phase 0 engine/WeChat/manual checks and Plan §3.3 remain the business prerequisites reported by WorkBuddy. This interface repair does not satisfy them or authorize subsequent app implementation. No historical production/Phase conclusion or V1 6.21/6.22 acceptance gate is changed.
