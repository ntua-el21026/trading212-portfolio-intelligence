# Phase 3 Operations and Resilience

**Status:** Accepted implementation design; measured exercises pending

Reuse PostgreSQL authority, Redis wakeups, outbox and worker families; data contract
bounds admission/retry/lease/retention. Production remains unauthorized/unverified.
One local Compose project, serial workloads, premium global concurrency one. Use one
container when enough. Inspect labels/consumers/exact paths before disposable cleanup;
keep current dependencies/images/source/evidence, never global prune/unrelated volumes.
Evidence lives outside checkout; remove duplicated generated artifacts only after
verified retention of originals. No claim of filesystem/VHD shrink from file deletion.

## Budgets/alerts

Documented synthetic targets: warm authorized read/list p95<=500ms, admission<=750ms,
<=12 SQL statements/bounded page; premium attempt<=240s and RSS<=512MiB at the
1,000,000 work-product ceiling. Measure representative and maximum workloads with
hardware/sample count/warm-cold/p50/p95, not unmeasured SLO claims.

Metrics use bounded operation/family/outcome only, no private identifiers/text/tokens.
Measure queue age, admission rejection, duration, lease expiry/retry/dead letter,
cleanup lag, provider failure/rate budget. Local alerts: eligible queue age>120s,
dead letter>0, cleanup lag>1h, repeated provider failures>=3, DB unavailable. Each
runbook links scoped inspection and retry after current authorization.

## Recovery

Seed synthetic retained jobs/results and record counts/hashes. Kill worker around
checkpoint/publication, expire lease, replay dispatch, lose Redis, interrupt DB and
restart full services. PostgreSQL/outbox recovers; stale fences cannot publish,
cancellation/revocation wins, no duplicate result/cash effect. Health alone is no proof.

Backup with PostgreSQL tooling to task-private artifact, recording schema/version and
sanitized counts. Restore to a genuinely empty named synthetic DB in the same service;
never reuse original tables. Validate migrations/FK/unique/check constraints, counts,
canonical financial digests, licenses and resumable jobs. Local RPO=captured committed
boundary, RTO target<=10min for frozen fixture; measure elapsed. No production SLA.

## Candidate machinery

Harden least-privilege images with source/tree, pinned locks and contracts. Retain
SBOM/build provenance and scanner database freshness/scope/exceptions, no blanket
suppression. Implement signing/verification and demonstrate ephemeral local keys,
wrong-source/tamper denial. No private key/token in evidence or production attestation
claim. Empty install/Phase2 upgrade must converge on one Alembic head.

CI deferred_by_owner/unverified. Public deployment/HTTPS/OAuth/ChatGPT registration,
production secrets/identity, provider licenses/live access, monitoring/backup/signing
and release/tag publication remain unauthorized external gates.
