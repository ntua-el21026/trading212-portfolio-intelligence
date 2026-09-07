# Phase 2 Operations Extension

**Status:** Accepted

**Date:** 2026-09-07

## Service topology and configuration

Retain PostgreSQL, Redis, API, worker, dispatcher, MCP and web. Reuse the fixed
worker and dispatcher for report and alert jobs; a separate scheduler/report
service requires a documented operational reason. PostgreSQL is authoritative
for target revisions, source snapshots, plans, reports, artifacts, rule versions,
evaluations, notifications, jobs and outbox intent. Redis is replaceable transport,
coordination and cache. A successful queue publish is not a completed job.

Default local mode uses deterministic synthetic inputs and existing local-only
authentication. Provider status identifies synthetic, configured, unavailable,
stale, partial and failed separately. Production configuration still fails closed
without the required identity and secret-manager setup. No command silently
switches synthetic inputs into a real account or enables Trading 212 Live.

Use existing `make bootstrap`, `make run-local`, `make migrate`, `make seed-demo`
and `make validate` entry points as the implementation extends them. Seed changes
are deterministic and idempotent; existing Phase 1 economic rows remain unchanged.
Inspect and record the migration/image/source version before starting services.

## Durable work and readiness

Fixed internal job kinds cover report generation, alert evaluation/delivery and
artifact expiry. Claim bounded batches with fenced leases, record attempt counts,
retry only classified transient failures, and retain safe dead-letter reasons.
Requests atomically persist input references and outbox intent. Acknowledgment
requires durable completion. Idempotent replay checks semantic input fingerprints.

Dispatcher readiness reflects a successful database/outbox cycle; worker readiness
reflects an actual consumer. Report/alert backlog, pending age, dead-letter count,
lease expiry, artifact expiry and source freshness are observable. No metric label
contains raw owner/account IDs, URLs, instruments, report names, email addresses,
user text or secret values. Use bounded operation/outcome/quality categories and
opaque audit references.

## Recovery procedures

| Failure | Required operational behavior |
|---|---|
| Bad target edit/publication | Recover by a new audited version from a known prior version; never mutate published history |
| Provider outage or bad source data | Retain last immutable snapshot with stale/failed coverage; isolate/reject revision and replay after contract correction |
| Missing benchmark or FX | Return explicit missing-coverage state; select only documented source-consistent observations before cutoff |
| Optimizer failure/infeasibility | Preserve request/input hash and safe reason; retry only failed work, never drop constraints or create orders |
| Stale X-ray sources | Preserve source dates/unresolved weight, degrade output and quality-gated alerts |
| Report generation failure | Recover the durable job after lease expiry; regenerate from pinned inputs; avoid duplicate completion/artifacts |
| Artifact storage failure | Keep job failed/retryable by category; do not issue success/download until durable bytes and digest exist |
| Alert or delivery backlog | Inspect bounded categories and lease/attempt state; retry via fixed handlers, preserve deduplication/cooldown identity |
| Unsafe webhook configuration | Disable external delivery, preserve in-app feed, require a reviewed safe configured destination |
| Credential rotation | Update only opaque server-side secret reference/configuration; never write credentials to business data or logs |
| Artifact expiry/deletion | Deny expired access immediately, then remove bounded expired bytes/grants and append safe audit metadata |

## Retention, migration and backup

Initial private report storage is bounded PostgreSQL BYTEA with explicit expiry;
no persistent signed provider URL is permitted. Cleanup uses bounded non-blocking
batches and owner-safe scope. Retain canonical manifests and audit according to
policy while clearly distinguishing deleted artifact bytes from unavailable input.
An optional object-store adapter must preserve the same authorization/licensing
and atomic-completion contract before deployment.

Apply migrations forward from `20260907_0008` and test old/new schema compatibility.
Immutable source and privacy-deletion migrations are not casually reversible.
Document any non-reversible operation before release; application rollback must
not restore signed URL retention or invalidate ownership constraints. Follow the
[existing backup/restore runbook](BACKUP_RESTORE.md); production backup restoration
remains an explicit external gate until actually tested.

## Acceptance and incident evidence

Use an isolated Compose project/ports/volume for stop/restart tests, never delete
unrelated volumes, and confirm all seven service states are stopped before restart.
Compare canonical hashes, economic counts, target/plan/job/evaluation/artifact
identities, and restored volume identity. Scan runtime files, logs, database rows,
metrics and rendered/exported artifacts with dynamically assembled synthetic
secret and URL canaries. Preserve safe evidence with exact source SHA/image IDs.
Do not infer production throughput, credentialed provider connectivity or public
MCP readiness from synthetic local acceptance.
