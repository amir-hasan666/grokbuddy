# GrokBuddy V1 review decision policy

Human amendment, 2026-09-23: Plan R1 PASS with no unresolved substantive Finding approves the Plan immediately. Plan R2 is required only after R1 NEEDS_CHANGES or BLOCK. This contract governs new Tasks frozen with `decision_policy_version=grokbuddy-v1-dual-round`. Older Tasks without this version keep their historical limits and semantics.

The wire verdicts are `PASS`, `NEEDS_CHANGES`, and `BLOCK`; the product label `BLOCKED` corresponds to a second-round effective `BLOCK`. Task Human Gate states are separate. Reviewer identity, asynchronous APPLY, immutable Review/history, Hub authority and input/profile hashes remain required.

| Type | Round | Valid verdict | Task transition | WorkBuddy action |
| --- | --- | --- | --- | --- |
| Plan | 1 | PASS | PLAN_APPROVED | Start coding inside the approved Plan scope. |
| Plan | 1 | NEEDS_CHANGES or BLOCK | PLAN_CHANGES_REQUIRED | Revise once, submit Plan V2 and R2. Preserve the original verdict. |
| Plan | 2 | PASS | PLAN_APPROVED | Start coding inside the approved Plan scope. |
| Plan | 2 | BLOCK | PLAN_HUMAN_REVIEW | Stop; show Plan V1, Grok R1, Plan V2 and Grok R2 reason. |
| Final | 1 | PASS | DONE / FINAL_REVIEW_PASS | Deliver method, files and tests. |
| Final | 1 | NEEDS_CHANGES or BLOCK | FINAL_CHANGES_REQUIRED | Repair once in approved scope, self-test and submit R2. |
| Final | 2 | PASS | DONE / FINAL_REVIEW_PASS | Deliver method, files and tests. |
| Final | 2 | BLOCK | FINAL_HUMAN_REVIEW | Show method, files, tests and reason as not accepted. |

R1 NEEDS_CHANGES/BLOCK requires at least one actionable Finding with evidence, scope and proposed correction. R2 accepts only PASS/BLOCK; any other result is rejected without Review/Finding business mutation. R2 BLOCK requires `blocker_category` (DIRECTION, CORE_REQUIREMENT, SECURITY or DATA), evidence and an unresolved blocking HIGH/CRITICAL Finding. These guards do not prove the Reviewer's substantive judgment.

New minor R2 points belong in `recommendations[]`, not actionable `findings[]`. A prior LOW Finding may receive `advisory=true, actionable=false` only via an explicit R2 Reviewer `ADVISORY` verification with evidence, reason and a retained recommendation. Its original status is not rewritten as VERIFIED or Human waiver; the original Finding and appended event remain visible. Other unresolved Finding statuses prohibit PASS. An inconsistent R2 PASS is rejected rather than downgraded to NEEDS_CHANGES.

Each new Review Request consumes one numbered round. The Task freezes this policy and absolute Plan/Final caps of 2/2. R1 PASS needs no R2. R1 revision may consume the remaining round once. Human budget, Continue, Modify and resume cannot create R3. Plan Human override cannot authorize coding without Grok Plan PASS on the V1 Task. If Human separately accepts a blocked Final result, DONE / HUMAN_OVERRIDE remains distinct from Grok PASS. A future three-round policy needs a separately approved version assigned only to future Tasks.

Timeout, delivery exhaustion, Reviewer failure and invalid result are technical conditions, never Reviewer BLOCK. Failed/timed-out RR status and stage-specific technical Gate reasons remain separate. Invalid results leave the RR pending until a valid result or deadline. Same-RR transport retry consumes no new round.
