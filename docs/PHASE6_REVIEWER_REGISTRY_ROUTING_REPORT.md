PHASE6-REVIEWER-REGISTRY-ROUTING: LOCAL PASS / WAITING HUMAN SWITCH DRILL

# Phase 6 Reviewer Registry / Active Reviewer Routing Report

Date: 2026-09-22 (Asia/Shanghai)

Scope: implement a non-secret Reviewer Registry and an active Reviewer default for future Review Requests only. This work does not reopen Step 6.20, does not establish Phase 6 PASS, and does not change the production Reviewer during implementation.

## AUDIT

### Human motivation and control boundary

- A long-lived WorkBuddy Reviewer conversation grows indefinitely, wasting tokens and increasing context contamination risk. A Reviewer must treat Hub ReviewRequest, Artifact, Finding and optional GitHub projection data as the formal inputs, not prior chat history.
- An administrator needs to create a fresh WorkBuddy Reviewer identity and route only later Review Requests by editing non-secret configuration and restarting the Hub.
- The active Reviewer is only a creation-time default. It is not authority to rewrite an existing ReviewRequest, Review, Finding, Audit row, delivery contract or Task state.
- Reviewer display names are operational labels, not security identities. The stable Hub `reviewer_actor_id` is the identity frozen in a ReviewRequest.

### Current identity layers

| Layer | Current implementation evidence | Security meaning |
| --- | --- | --- |
| `display_name` | `actors.name`; current formal actor was registered with the WorkBuddy Reviewer display name | Mutable human-facing label; must not be used as `expected_reviewer_actor_id` |
| `reviewer_actor_id` | `actors.id`; `ReviewService.request_review` resolves a registered Reviewer and writes the supplied ID into `envelope.expected_reviewer_actor_id` | Stable Hub machine principal and immutable RR snapshot |
| credential principal | Windows Credential Manager target `GrokBuddy/GROKBUDDY_GROK_REVIEWER_TOKEN`, injected into process env `GROKBUDDY_GROK_REVIEWER_TOKEN` by the existing launcher | Shared phase-one endpoint credential; no secret value is stored in repository configuration |
| connector / execution identity | `actors.reviewer_type`, `provider_id`, `agent_id`, `server_id`; inbound events additionally carry `run_id` | Adapter and execution correlation. Current bearer token is not yet a distinct per-Reviewer credential principal |

The current WorkBuddy integration exposes agent/server execution metadata and Hub validates it, but this repository does not prove that separate Bot conversations have independently revocable credentials. Therefore the first implementation may provide logical actor-to-execution mapping while retaining the shared credential, but it must not claim credential-level isolation.

### ReviewRequest creation and persistence

- `src/grokbuddy/application/reviews.py::ReviewService.request_review` currently receives `reviewer_id`, resolves an enabled `Role.REVIEWER` actor, rejects Builder/Reviewer provider identity equality, and snapshots the ID into `envelope.expected_reviewer_actor_id` before contract validation and persistence.
- The entire envelope is stored in `review_requests.data`; the same envelope hash and metadata are copied to the outbox. No later configuration lookup participates in that snapshot.
- `src/grokbuddy/interfaces/gateway.py` supplies `runtime.default_reviewer_actor_id` only when the caller omits `reviewer_id`. Explicit reviewer IDs remain a compatibility/test path.
- The formal stdio entry point currently derives that default from `config/grokbuddy.service.json::reviewerActor`; isolated runtimes default to `mock-reviewer`.

### Dispatch, intake and callback enforcement

- `Dispatcher._claim` filters by each RR envelope's frozen `expected_reviewer_actor_id`.
- `GrokBotReviewerAdapter._target`, `RemoteReviewerIntakeWorker`, `ReviewerWebhookWakeWorker`, `GrokRoutingService.grok_request` and `validate_grok_event_route` all bind delivery/read/wake/event handling to the RR snapshot and the registered actor/agent/server mapping.
- `EventService.handle_one` rejects an inbound actor that differs from `expected_reviewer_actor_id`; a valid result also has to declare the same reviewer identity and match the frozen RR fields.
- `REVIEWER_HTTP` versus `GITHUB_COMMENT` is frozen on RR creation. A later binding or `FUTURE_REQUESTS_ONLY` route does not rewrite the existing channel.
- These consumers already use the RR snapshot rather than the current service default. Active Reviewer configuration therefore belongs only at the creation/default-selection boundary.

### GitHub binding and route state

- `github_bindings` persists a `reviewer_actor_id` as binding metadata.
- `grok_reviewer_routes` persists a task-scoped `reviewer_actor_id`, `agent_id`, `server_id` and `applies_to=FUTURE_REQUESTS_ONLY`; route rows are immutable.
- A matching binding/route selects `GITHUB_COMMENT`. A formal unbound v2 request selects `REVIEWER_HTTP`. Neither path authorizes rewriting an existing RR when a new active Reviewer is configured.

### Actor registration and current production observation

- `GrokRoutingService.register_reviewer` is the existing audited registration path. It creates an immutable `Role.REVIEWER` actor with stable Hub ID and Grok provider/agent/server mapping; conflicting re-registration fails closed.
- A read-only open of `var/github-manual/hub.db` on 2026-09-22 observed registered Reviewers `grok-reviewer-b` and `mock-reviewer`, no `PENDING` or `IN_PROGRESS` ReviewRequest, and existing historical `FUTURE_REQUESTS_ONLY` routes for `grok-reviewer-b`. No database DML was performed.

### Configuration and hard-coded defaults

- The formal service config currently contains `reviewerActor: grok-reviewer-b`; `Start-GrokBuddyHub.ps1`, `scripts/grokbuddy_composite.py` and `scripts/grokbuddy_mcp.py` use it to assemble the production path.
- `LocalRuntime` and MCP parser defaults intentionally use `mock-reviewer` for isolated/test runtimes. Tests also use explicit fixture actors. Those test defaults are not production configuration.
- There is no current non-secret Reviewer registry, no configured display/connector mapping file, and no startup validation that an active entry is known and enabled.

### Credential, wake and production constraints

- The existing launcher reads the formal Reviewer token from Windows Credential Manager and injects it only into the process. The token value is not read or recorded by this work.
- Webhook wake and `REVIEWER_HTTP` are already wired to the current formal actor and frozen RR snapshot. Registry work must change only how the formal actor/configuration is selected at restart, not the credential target, endpoint protocol, wake receipt semantics or delivery channel rules.
- The production default after this implementation must remain `grok-reviewer-b`. Local tests and registry validation cannot establish a real WorkBuddy switch drill or a new Bot's technical identity.

## DESIGN

### Source of truth and reload

- `config/reviewer-registry.json::activeReviewer` is the Reviewer selection source.
- `config/grokbuddy.service.json::reviewerRegistryPath` locates that registry. The existing `reviewerActor` field remains temporarily as a compatibility drift assertion because parallel production-wiring checks still consume it. It does not select or override the active Reviewer. If it differs from the registry active value, the formal launcher, service loader and stdio default path fail closed.
- Reload is deliberately `RESTART_REQUIRED`. The Registry is loaded once during formal process startup. Editing a file does not mutate a running Hub and does not change a ReviewRequest already committed.
- The current registry and compatibility assertion both remain `grok-reviewer-b`; this implementation does not switch production to a new Bot.

### Strict non-secret registry

Registry version 1 contains:

- stable actor key;
- mutable operational `displayName`;
- `enabled` eligibility for the active entry;
- non-secret `credentialRef`;
- connector `type`, real `agentId` and `serverId`.

The loader rejects missing/malformed/unknown fields, unsupported versions or connector types, invalid identifiers, duplicate execution identities, missing/unknown/disabled active entries, repository path escape and service/registry drift. Unknown fields such as an accidentally pasted `token` are rejected. The production composite additionally requires the active entry to reference the existing `GrokBuddy/GROKBUDDY_GROK_REVIEWER_TOKEN`; no new Credential Manager wiring was introduced.

### Actor registration and immutable identity

At formal startup the Registry is applied through `GrokRoutingService.ensure_registry_reviewer`, an audited Application path. A missing actor is created using its stable Hub ID and provider/agent/server mapping. An existing actor must match the immutable technical identity or startup fails. Changing only the Registry display label does not rewrite the append-only actor row and cannot change its security identity.

No table, column or migration was added. Existing actors, routes, ReviewRequests, Reviews and Audit rows are not updated.

### Creation and consumption rules

- Formal composite and formal stdio processes set `LocalRuntime.default_reviewer_actor_id` from the validated active Registry entry.
- `ClientGateway` uses that value only when a request omits `reviewer_id`; `ReviewService` performs the existing actor/independence checks and freezes the selected ID into the new RR envelope.
- Isolated runtimes and explicit test fixtures retain `mock-reviewer`. The formal runtime never falls back from an invalid Registry to Mock or to the legacy assertion.
- Dispatch, HTTP intake, webhook wake, request reads and event/result validation continue to read the RR's frozen `expected_reviewer_actor_id`. They never consult current `activeReviewer` for an existing RR.

### Credential and execution identity boundary

Phase one retains the existing shared Reviewer bearer token and CredMgr target. Registry `credentialRef` is an extension point, but an alternate active target currently fails startup because no per-Reviewer secure injection/endpoint binding has been authorized or implemented. Connector agent/server values distinguish logical actors and execution correlation; `run_id` remains per event. This is not independently revocable credential isolation.

## CHANGES

| File | Change |
| --- | --- |
| `config/reviewer-registry.json` | New strict registry; production active remains `grok-reviewer-b` with the already verified WorkBuddy connector mapping |
| `config/grokbuddy.service.json` | Adds only `reviewerRegistryPath`; preserves current production actor, runtime, wake and Supervisor values |
| `src/grokbuddy/infrastructure/reviewer_registry.py` | Strict loader, service drift guard and audited registration orchestration |
| `src/grokbuddy/application/grok_routing.py` | Adds registry actor ensure/identity verification; no route or RR mutation |
| `scripts/grokbuddy_composite.py` | Formal runtime selects and registers the active Reviewer from Registry; explicit actor remains an isolated compatibility option |
| `scripts/grokbuddy_mcp.py` | Formal stdio default reads the same Registry; non-formal runtimes remain Mock |
| `scripts/windows/Start-GrokBuddyHub.ps1` | Validates registry presence/drift and passes its path; CredMgr mappings and wake settings are unchanged |
| `scripts/validate_reviewer_registry.py` | Safe non-secret configuration probe |
| `tests/test_phase6_reviewer_registry_routing.py` | Registry, switch-snapshot, mismatch, startup and production-default matrix |
| `docs/REVIEWER_REGISTRY_OPERATIONS.md` | Human preparation, validation, restart, switch, verification, retirement and rollback runbook |
| this report | Audit, design, evidence, risks, Human steps and bounded status |

No direct Hub database DML, schema migration, secret read, external Bot call, production restart, Git push or production ReviewRequest creation was performed.

## TESTS

### Reviewer Registry matrix

Command:

```powershell
.\.venv-phase0\Scripts\python.exe -m pytest -q tests/test_phase6_reviewer_registry_routing.py
```

Result: `8 passed in 4.99s`.

Covered assertions:

1. active 001 creates RR-A with expected 001;
2. restart/config active 002 creates RR-B with expected 002 without DB update;
3. RR-A envelope remains byte-for-byte logically equal and expected 001;
4. actor 002 is rejected when validating an event route for RR-A;
5. unknown, disabled or missing active fails;
6. malformed Registry and secret-like unknown field fail;
7. service/Registry actor drift fails rather than overriding;
8. composite startup selection rejects invalid Registry;
9. current formal config creates a real local test RR whose snapshot remains `grok-reviewer-b`;
10. production Registry contains only declared non-secret fields and the existing credential target reference.

### Full repository regression

Command:

```powershell
.\.venv-phase0\Scripts\python.exe -m pytest -q `
  --deselect=tests/test_phase6_reviewer_webhook_wake.py::test_missing_wake_configuration_skips_worker_and_receipt
```

Result: `818 passed, 1 deselected in 152.45s`.

The one deselected test is a pre-existing parallel wake-session drift: current `config/grokbuddy.service.json` already configures non-empty wake environment names, while that test asserts both values are empty. A preliminary combined run produced `35 passed, 1 failed` with only that assertion. Registry work did not change, disable or repair wake configuration because this session is explicitly isolated from that work.

### Static and configuration checks

- `python -m py_compile` for the new loader/probe and modified Python entry points: PASS.
- `python scripts/validate_reviewer_registry.py`: PASS; safely reported active `grok-reviewer-b`, one Reviewer and `RESTART_REQUIRED` without reading a secret.
- PowerShell parser on `Start-GrokBuddyHub.ps1`: PASS.
- JSON parse for service and Registry files: PASS.
- Strict UTF-8/no-BOM check for new Registry/code/test/docs files: PASS.
- `git diff --check`: PASS (line-ending conversion warnings only).
- `scripts/validate_phase0.py`: `218/219`; only `phase0-no-core-source` fails because that historical Phase 0 validator requires an empty core-source tree. This implemented repository necessarily violates that obsolete Phase 0-only premise; the result is not used as Registry PASS evidence. External gate remained BLOCKED and no live integration ran.

### Evidence limits

All PASS results above are local/static or isolated runtime evidence. They do not prove a new WorkBuddy Bot exists, a new credential identity is distinct, the Windows service has restarted with these files, webhook wake reaches a new Bot, or a real production switch succeeds.

## RISKS

- The shared phase-one bearer credential can authenticate the formal Reviewer surface but cannot independently revoke one configured Reviewer. Agent/server validation provides logical/execution correlation, not cryptographic binding of a credential to one actor.
- The current production composition starts one active technical adapter. Switching while an old RR is still active would leave that old snapshot intact and correctly reject the new actor, but the old Bot path would no longer be the active process path. The runbook therefore requires all pre-switch RRs to be terminal before restart. Multi-adapter concurrent draining is not claimed.
- Registry startup may add a previously unknown actor through the audited Application service. A conflicting existing actor is fail-closed; operators must not work around it with direct DB DML.
- `reviewerActor` is temporarily duplicated as a drift assertion for compatibility. Both configuration values must be updated together until later authorized cleanup removes the assertion and its consumers.
- Existing dirty worktree changes from the Supervisor/wake/6.20 sessions remain interleaved in shared files. This work preserved them and did not rewrite their reports; a later commit must review/stage only the intended combined files.

## HUMAN STEPS

The executable procedure is [Reviewer Registry Operations](REVIEWER_REGISTRY_OPERATIONS.md). The required production switch drill is:

1. provision the new WorkBuddy Reviewer and obtain real non-secret agent/server IDs;
2. add a unique stable Hub actor entry while keeping the current active unchanged;
3. run the non-secret Registry validation;
4. confirm no old RR is `PENDING` or `IN_PROGRESS`;
5. change Registry active and the compatibility assertion together;
6. perform the existing controlled Hub restart and `/health` plus `/ready` probes;
7. create one new RR through the formal path without explicit `reviewer_id` and verify the new snapshot;
8. verify an old RR snapshot is unchanged;
9. complete a real Reviewer request/event round trip and verify actor, agent, server and run identity;
10. only then mark the old entry disabled or perform the documented configuration rollback.

Rollback changes only future selection. It must not update, migrate, delete or revive a historical RR.

## STATUS

`PHASE6-REVIEWER-REGISTRY-ROUTING: LOCAL PASS / WAITING HUMAN SWITCH DRILL`.

- Safe to keep current production default: **yes, configuration remains `grok-reviewer-b` and local regression proves new local RRs retain that snapshot**.
- Safe to declare a new Reviewer production switch complete now: **no**. No new Bot/technical identity was supplied, no production restart/probe or real round trip was authorized, and per-Reviewer credential isolation is not implemented.
- This result is not a Step 6.20 rerun, does not alter its evidence, and is not Phase 6 PASS.
