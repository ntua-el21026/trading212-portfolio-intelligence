# ADR-0014: Private Reproducible Reports

**Status:** Accepted

**Date:** 2026-09-07

**Decision authority:** Current owner's Phase 2 design-closure assignment

## Context

PDF, CSV, JSON, and XLSX reports must match canonical analytical results, survive
worker restarts, enforce owner/account permissions, and expire predictably.
Private financial data cannot live at public URLs or depend on provider signed
links. Generated binary metadata may vary even when underlying report content
is identical, so byte identity and analytical reproducibility need separate
evidence. Optional paid data licenses may restrict persistence or redistribution.

## Decision

Adopt [Phase 2 methods, section 7](../analytics/PHASE_2_METHODS.md#7-private-reports-and-exports)
and `report_manifest_v1` version `1.0.0`. Ten fixed report types and four
formats select authorized canonical service outputs under fixed section/input
schemas. There are no arbitrary templates, URLs, formula fields, or raw-provider
exports. Every report pins source cutoff, period/currency, immutable analytical
and source references, target/plan versions, renderer/schema versions,
provenance, licensing, assumptions, coverage, reconciliation, and quality.

Use PostgreSQL BYTEA as the default private artifact store. Bound each artifact
to 10 MiB, all formats of one job to 25 MiB, and each selected dataset to
100,000 rows, 64 columns, and 4,096 characters per text cell. At most four
formats may be requested. Bounds are checked during reads/generation; overflow
is a typed failure, never silent truncation. A typed external storage port may
be configured later only with equivalent private access, integrity, expiry,
and orphan cleanup. Local correctness requires no external storage credentials.

Job creation authorizes scope, pins inputs, records owner-scoped idempotency,
and enqueues a typed `reports.generate.v1` transactional outbox record.
Standalone dataset exports use `exports.generate.v1`. PostgreSQL owns durable
execution state; Redis is dispatch coordination only. Fenced 60-second leases
with 15-second heartbeat permit restart recovery and reject stale completion.
Reuse bounded outbox publication (eight attempts) and consumer execution
(four attempts), sanitized errors, dead-letter handling, and stable job identity.
Final manifest plus all requested artifacts commit atomically; duplicate
delivery cannot create a second finalized artifact for the same job/format.

The canonical manifest is independently serializable and SHA-256 hashable. It
excludes generated job IDs, execution/expiry timestamps, storage addresses,
and access grants. Its selected content and options remain identical on replay.
Each artifact has a separate actual-byte digest. PDF generation timestamps are
permitted only outside the semantic manifest; this design makes no untested
byte-identical PDF claim. Renderers never recompute financial values.

Default expiry is seven days, requested bounds are one through 30 days.
Downloads require current owner/account and selected-section authorization,
plus a five-minute-or-shorter owner/artifact-bound grant where the download
contract uses one. Store only the grant digest; send the raw token through the
dedicated header, never a logged query string or MCP response. Enforce expiry
before reading bytes even if cleanup has not run. Bounded idempotent cleanup
removes expired bytes/grants and retains only permitted audit/manifest tombstones.
Use fixed MIME, safe server-generated filenames, private/no-store, and `nosniff`.

CSV quotes/escapes fields and neutralizes formula initiators under a documented
tested import policy; downstream spreadsheet transformations can weaken CSV
escaping, as described by [OWASP](https://owasp.org/www-community/attacks/CSV_Injection)
(reviewed 2026-09-07). XLSX stores authoritative decimals and untrusted strings
as explicit text and contains no formulas, macros, or external links. JSON
retains canonical decimal strings and typed unavailable states. Denied or
unknown license permissions block the selected use; an explicitly redacted
report has a different recorded selection and manifest. Credentials, signed
URLs, raw payloads, and their derivatives are absent from all formats.

## Consequences

Bounded BYTEA storage provides transactionally consistent, restart-durable local
reports without another required service or volume. Artifact growth is
controlled by explicit limits and expiry; large requests must be narrowed or
use an explicitly selected summary. PostgreSQL backups remain private financial
data and follow existing backup/access/retention controls.

Report reproducibility can be proved independently of renderer metadata.
License revocation may deny future downloads while a permitted manifest/audit
tombstone remains; old access grants never override current authorization.
Tests must cover canonical API/MCP parity, manifest replay, actual format
parsing, CSV/XLSX formula canaries, all bounds, cross-owner/account denial,
expired grants/artifacts, duplicate jobs, crash/lease recovery, stale workers,
atomic completion, deletion, and license denial. Passing evidence is separate
from this design acceptance.

## Rejected alternatives

- Public storage, persisted signed URLs, or token-only downloads: inadequate
  scope isolation and incompatible with the export-URL privacy boundary.
- Local untracked files as authoritative artifacts: incomplete restart/backup
  and transactional-completion semantics.
- An external object store as a mandatory local dependency: adds configuration
  and credentials without necessity for the accepted bounded artifact workload.
- Treating a PDF byte hash as the only reproducibility proof: confuses binary
  metadata with canonical analytical content.
- Silent row/byte truncation or silently removed licensed sections: falsely
  represents an incomplete export as the requested report.
