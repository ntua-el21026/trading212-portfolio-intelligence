# Phase 3 bounded Checkpoint B qualification, 17 November 2026

**Owner:** Michail Athanasios Peppas  
**State:** In progress; Checkpoint B incomplete; independent acceptance pending.

## Authority and source

The live, local and remote-tracking `main` baseline is
`a9f4164225750312d0d3dd0e4440d9bf2a41890f`, tree
`76a02391d9b6be35149cab69c8ecf5fc533b4130`. Its only changes since the
preceding qualification delivery are three draft UI design documents. They remain
planning material. This package does not authorize the redesign, P3-10, CI,
providers, production, licensing changes or distribution.

All 30 acceptance rows and 48 scenarios remain formally pending, zero accepted.
The [preceding qualification](PHASE_3_FINAL_LOCAL_QUALIFICATION_20261116.md)
and [complete historical traceability](PHASE_3_FINAL_LOCAL_TRACEABILITY_20261116.md)
retain their original failures, focused recoveries and source identities.

## Admission: bounded investigation closed without correction

All three executions use unchanged clean baseline source, the existing PostgreSQL
image, unchanged configuration and quotas, ten genuine admissions and completed
jobs, thirty reads, and the original nearest-rank percentile calculation.

| Execution | Admission p95 s | Read p95 s | Maximum SQL | Exit |
| --- | ---: | ---: | ---: | ---: |
| Bare original B0 | 1.919321170 | 0.658690008 | 12 | 1 |
| Minimal diagnostic D | 0.991885823 | 0.314522988 | 12 | 1 |
| Bare original B1 | 0.774257422 | 0.318458853 | 12 | 1 |

The limits remain 0.750 s, 0.500 s and 12 statements. No sample is removed.
B0 also fails the read limit. The diagnostic observes process CPU at admission
edges and natural GC through a bounded callback; it does not wrap SQL,
authorization, encoding or worker functions. All 80 original clock calls occur.
Generation-2 GC overlaps diagnostic admissions 1, 4 and 8 by about 0.221, 0.230
and 0.224 s. The first diagnostic admission takes 0.992 s wall, 0.720 s process
CPU and 0.243 s overlapping GC; the fastest takes 0.541, 0.417 and 0.011 s.
These overlapping costs are not additive or representative bare stage timings.

A separate clock microcalibration observes a median 6.094 microseconds additional
bookkeeping per batch of 80 calls. It does not quantify import, heap or natural-GC
schedule effects. No estimated overhead is subtracted. Process CPU includes
worker threads; wall minus process CPU does not identify SQL, commit, locks or
scheduling individually. Different fixtures have synthetic identities and the
normal lifecycle; they are not identical physical database snapshots. An initial
optional dependency-metadata probe fails before its database connection because
`orjson` is absent; subsequent snapshots record absence explicitly. No dependency
is installed. The initial GUC snapshot is unavailable; later actual GUC snapshots,
container identity and source bookends are retained.

First-use CPU/GC and temporal environment variability remain supported
inferences, not a verified production defect. The investigation stops after the
three authorized cohorts. No speculative optimization, warmup, timeout, workload,
quota, database-setting or threshold change is made.

Private execution receipts: `admission-bare-b0-command/receipt.json`,
`admission-diagnostic-d-command/receipt.json`,
`admission-bare-b1-command/receipt.json`. The private analysis preserves all samples,
CPU/GC rows, environment snapshots and observer limitations.

## Configured SAST parser correction

Semgrep 1.175.0 reports `PartialParsing`, code 3, for the inline generic module
import type in `apps/web/tests/research-report-actions.test.ts`. The original
single-file scan reproduces the historical warning. Its reported line/column
points to the generic-call suffix, but reported offsets disagree with whole-file
byte positions; this diagnostic limitation is retained.

Naming that exact type as `ApiContractsModule` preserves the runtime expression
and all assertions. An isolated export comparison under the same scanner, rules
and exclusions changes the actual scanner exit from 3 to 0, with zero findings or
errors. The installed TypeScript transpiler reports byte-identical emitted
JavaScript for original and corrected files. All 12 affected tests, strict web
typing, formatting and lint pass.

The actual full `make sast-check` invocation then passes, exit 0 in 122.627 s:
all seven configured rules scan 996 files with zero findings. This is a manifested
working-source result at parent baseline `a9f4164`, source manifest
`89de16d9c05cf51d60960a6215160dce1828804d2b1c7f5375a30fd46b2a9c8b`.
The command's broader discovery count is 1,047; its configured selected scope
remains 996. No targets, rules, scanner settings, excludes or policies change.

Private receipts: `sast-failed-file-metadata-02`,
`sast-type-alias-candidate-01`, `sast-type-alias-unit-01`,
`sast-type-alias-web-types-01`, `sast-type-erasure-01`,
`sast-type-alias-format-01`, `sast-type-alias-lint-01`,
`sast-full-configured-01`, each with `receipt.json`. Helper completion exits and
actual scanner exits remain separate. Secret-scanner failures are not changed
by this SAST result.

## Remaining qualification

Browser Back lifecycle diagnosis, a current-source paired build comparison,
focused Python prerequisite checks, one complete compatible native coverage
attempt, security closure and complete traceability reconciliation remain pending
in this continuing package. Historical scanner, browser, coverage and build
failures remain visible. No complete current-SHA validation pass is claimed.

The retained build comparison includes generated private framework keys,
expiration clocks, action identities and real execution traces. A safe correction
cannot make private keys predictable or exclude substantive artifacts. Any change
to that artifact contract requires a separate owner decision. A historical failed
pair is not current-source qualification.
