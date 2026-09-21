---
name: architecture-gate
description: Review this Collaboration Hub repository's architecture evidence and phase gates when assessing readiness or architecture changes; record unresolved external capability evidence without starting another planning lifecycle.
---

# Architecture gate

Read [AGENTS.md](../../AGENTS.md) for repository rules and [IMPLEMENTATION_PLAN.md](../../IMPLEMENTATION_PLAN.md) for the requested phase's Gate. Do not duplicate those rules in this skill.

For an architecture review, trace each affected requirement to the authoritative design document, a concrete contract/fixture, and the actual verification record. Use [capability verification](../../docs/CAPABILITY_VERIFICATION.md) to distinguish official documentation, local observations and current-account tests. An unavailable external test is an explicit gap, not an inferred pass.

Inspect boundaries in [ARCHITECTURE.md](../../ARCHITECTURE.md), [DATA_MODEL.md](../../DATA_MODEL.md), and [STATE_MACHINE.md](../../STATE_MACHINE.md) only as relevant. Check transaction/identity/revision interactions, especially late events, dispatch ambiguity, final verdict versus approvals, and cross-mode deduplication.

Return a Gate table with evidence paths, pass/blocked/not-run status and exact missing evidence. Link any proposed design interpretation for human review. During Phase 0, update its existing report; do not launch a second planning phase or implement the next phase to prove readiness.
