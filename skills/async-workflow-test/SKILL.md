---
name: async-workflow-test
description: Design or run this repository's asynchronous review tests for request receipts, events, timeouts, retries and cross-mode deduplication, using the current authorized phase and available implementation.
---

# Async workflow test

Read [AGENTS.md](../../AGENTS.md), [ASYNC_REVIEW_SEQUENCE.md](../../docs/ASYNC_REVIEW_SEQUENCE.md), and the relevant cases in [TEST_MATRIX.md](../../docs/TEST_MATRIX.md).

In Phase 0, review the sequence, transaction boundaries and test specifications; run only existing document/contract checks. Do not implement a service merely to make an architecture test pass. State plainly that fixtures cannot prove runtime asynchrony.

When a later implementation phase is authorized, use MockReviewer and a controlled clock/transport. Observe the request receipt before releasing a completion event, restart around outbox/inbox commits, race timeout against completion, and deliver one result through both ingress modes. Verify durable state, audit, stable Finding IDs and absence of extra dispatches rather than elapsed sleep alone.

For the last allowed round test both PASS and non-PASS. Distinguish transport retry from new evaluation. For uncertain external delivery verify escalation/reconciliation rather than blind resend. Never call real Grok or publish test messages unless that phase's external testing is explicitly authorized.

Return commands, observable assertions, pass/fail/not-run results and evidence paths. Keep mock results separate from current-account/provider results.
