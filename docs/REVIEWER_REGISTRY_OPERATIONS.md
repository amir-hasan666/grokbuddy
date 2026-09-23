# Reviewer Registry Operations

This runbook covers only the non-secret Reviewer Registry. It does not authorize a production switch, create a WorkBuddy Bot, change Credential Manager wiring, rerun Step 6.20, or establish Phase 6 PASS.

## Current production default

- Service config: `config/grokbuddy.service.json`
- Registry: `config/reviewer-registry.json`
- Active stable Hub actor: `grok-reviewer-b`
- Display label: `workbuddy审核员`
- Credential Manager target remains `GrokBuddy/GROKBUDDY_GROK_REVIEWER_TOKEN`
- Reload mode: controlled Hub restart; there is no hot reload

`reviewerActor` in the service config is retained only as a compatibility drift assertion. `activeReviewer` in the Registry is the selection source. They must match or formal startup fails closed; neither silently overrides the other.

## Validate without reading secrets

```powershell
.\.venv-phase0\Scripts\python.exe .\scripts\validate_reviewer_registry.py
```

The probe prints only the active stable actor, display label, non-secret credential target reference, registry path, reviewer count and `RESTART_REQUIRED`. It does not access or print a credential value.

## Prepare a new Reviewer

1. Create the WorkBuddy Reviewer outside GrokBuddy and record its real non-secret `agentId` and `serverId`. A display name alone is insufficient.
2. Choose a new stable Hub actor ID such as `workbuddy-reviewer-002`. Never reuse an old actor ID for a different agent/server identity.
3. Add a Registry entry with `displayName`, `enabled: true`, the existing phase-one `credentialRef`, and the real connector mapping. Do not paste a token, webhook key or secret into JSON.
4. Keep `activeReviewer` unchanged and run the validation command. Malformed fields, duplicate execution identities and unknown/disabled active entries fail closed.
5. Confirm through the formal Hub query surface that no old ReviewRequest is `PENDING` or `IN_PROGRESS`. The current production composition starts the configured active technical adapter; switch only after old requests are terminal so an unfinished old RR is not operationally orphaned.

The controlled startup calls the existing audited actor-registration use case. It does not issue direct database DML and it rejects a conflicting immutable provider/agent/server mapping.

## Switch future requests

1. Set Registry `activeReviewer` to the new stable actor ID.
2. Set service `reviewerActor` to the same ID as the compatibility drift assertion.
3. Run the non-secret validation command again.
4. Use the existing controlled Hub task restart procedure. Do not alter the existing Reviewer Credential Manager target, `REVIEWER_HTTP`, webhook wake settings, MCP surfaces or Supervisor topology.
5. Run the existing `/health` and `/ready` production probes.
6. Create one new ReviewRequest through the ordinary formal WorkBuddy/Hub path without an explicit `reviewer_id`. Verify its envelope has `expected_reviewer_actor_id=<new stable actor>`.
7. Read a pre-switch RR and verify its envelope still contains the old actor. Do not update the database or recreate the old request.
8. Complete a controlled Reviewer read/event round trip and verify the real `agentId`, `serverId` and `runId` against the new registry mapping before declaring the switch drill passed.

An explicit `reviewer_id` remains available for compatibility and isolated tests. Administrators should omit it on the normal production path so the validated active Registry entry is snapshotted.

## Retire and roll back

- Retire an old entry only after all its frozen RRs are terminal. Keep the entry for audit readability and set `enabled: false`; a disabled entry cannot be active.
- To roll back future routing, restore both `activeReviewer` and the service compatibility assertion to the prior actor, validate, and restart.
- Configuration rollback affects only later RR creation. It does not and must not rewrite any RR that already snapshotted either actor.
- Code rollback is a normal branch rollback. It must not include DB DML, actor deletion, ReviewRequest mutation or Audit rewriting.

## Known phase-one limitation

All configured WorkBuddy Reviewers currently reference the existing shared Reviewer credential principal. Agent/server validation gives logical actor and execution correlation, but not independently revocable per-Reviewer bearer credentials. A one-Reviewer-one-Credential-Manager-target design remains future work and is required before claiming credential-level isolation.
