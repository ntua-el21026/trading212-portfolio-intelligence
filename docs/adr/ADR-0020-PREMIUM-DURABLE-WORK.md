# ADR-0020 — Bounded Premium Work on the Existing Durable Pipeline

**Status:** Accepted implementation design; verification pending

**Date:** 2026-09-14

**Authority:** Owner's Complete Phase 3 assignment

## Decision

Use the existing PostgreSQL application-command, transactional outbox, lease,
fencing, audit and retention patterns for premium risk/scenario/projection work.
The [Phase 3 data contract](../architecture/PHASE_3_DATA_MODEL.md) defines normalized
records, concrete fixed task names, admission ceilings and publication obligations.
Keep the existing worker/dispatcher and one local running premium job. Redis is
replaceable coordination; it cannot own job identity or financial results.

Published definitions and captured inputs are immutable. Projection checkpoints
are keyed by absolute path index and current job fence, not worker/chunk identity.
Same canonical input/seed/model/numeric profile produces the same final financial
result after different chunking/retries. Final publication requires the whole
requested simulation population and normalized/canonical reconciliation in one
transaction. A timeout or cancellation cannot certify an incomplete prefix.

Current principal grants and source entitlements are checked at every execution,
resume, read, export and download. Previously queued authorization grants no
permanent right. Idempotent retry retains the original input, job and expiry;
it cannot select new sources, reset quotas or extend source retention.

## Consequences

Pure calculations remain directly testable, while production calls use durable
bounded admission. Normalized relational records make ownership and immutability
independently testable. Source expiry must inventory all checkpoint/result/report
copies and share existing physical cleanup budgets. New public APIs expose only
the fixed business commands, never a generic task dispatcher.

Reject an additional queue/worker service, Redis-only truth, all-results-in-memory
unbounded jobs, mutable published assumptions and completion after fence loss.
The existing pipeline gains typed participants; it does not gain broker writes.
Required evidence covers real PostgreSQL concurrency, restart and Redis loss,
cancellation, grant revocation, partial checkpoints, stale workers, retention,
clean install/upgrade and independent synthetic restoration before local acceptance.
