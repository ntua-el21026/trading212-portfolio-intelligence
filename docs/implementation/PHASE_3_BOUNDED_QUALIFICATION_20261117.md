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

## Browser Back: verified waiter and account-intent corrections

The first lifecycle diagnostic blocks on renderer evaluation while the response
is held and reaches the original 120-second test deadline. It does not prove the
product's cause. A corrected diagnostic uses browser-process history and passive
network events during the hold. Chromium cancels the secondary document request,
commits the previous primary-account Holdings history entry, and changes its
actual history index from 4 to 3 before release. Playwright's generic `goBack`
waiter instead rejects the cancelled older request with `ERR_ABORTED`.

Using the same native Chromium history command for the exact previous entry lets
the original assertions execute. That unchanged-production probe then fails:
the URL identifies the primary account while the selector retains the secondary
account. The provider's pending switch intent survives same-document history.
The minimal application correction clears that intent on `popstate` and removes
its exact listener on unmount. URL selection, authorization and private view
masking remain authoritative. Five new regressions initially fail alongside six
passing existing cases; all eleven pass after correction. They cover restoration,
late secondary payload masking, form-state isolation, malformed/duplicate/foreign
selections and StrictMode cleanup.

An intermediate observer-based Back helper reaches the original global timeout
on every viewport. Each complete workspace invocation contains four passes and
one failure: **12 passes and 3 timeouts overall**. Its artifacts do not identify
which observer or cleanup operation blocks; that attribution remains unresolved.
The final helper uses the already demonstrated native browser-process protocol,
confirms the exact history entry and Playwright's actual frame URL, retains the
original shared 15-second navigation bound and all original assertions, and adds
positive proof that Holdings is visible. Fixed stage annotations contain no
payloads, URLs or credentials. No assertion accepts an abort; no retries or skips
are added. The genuine response remains held until after the Back assertions,
then the original late-response checks execute.

Only the three failed Back cases are repeated on the unchanged application:

| Viewport | Actual result | Wrapper seconds | Receipt |
| --- | --- | ---: | --- |
| Desktop | PASS, 1 case | 56.168 | `account-history-back-only-desktop-05/receipt.json` |
| Tablet | PASS, 1 case | 51.137 | `account-history-back-only-tablet-05/receipt.json` |
| Mobile | PASS, 1 case | 50.897 | `account-history-back-only-mobile-05/receipt.json` |

All three share working-source manifest
`5469a1757ab799cf88709d4ff8164251d538af5a884f6e3631bdd42c3563df77`
at parent `9ffe93452a86155b24b7945698981a56e2c8d696`. The production build
`account-history-current-build-normal-retry-04` contains the same corrected
application input; later edits affect only browser-test orchestration. The failed
workspace matrix remains failed, separate from these focused recoveries. Neither
it nor the preceding complete API matrix becomes a passing aggregate.

Original execution evidence remains in `browser-back-lifecycle-desktop-01`,
`browser-back-lifecycle-desktop-02`, `browser-back-target-entry-desktop-03`,
`account-history-unit-red-01`, `account-history-unit-green-02` and the three
`account-history-workspace-*-04` receipts and reports. Explicit ESLint configuration
corrects an initial invocation that searched outside its workspace; no lint rule
or exclusion changes.

## Dependency advisory and actual build outcomes

The pinned Next.js 16.4.1 build emits an agent upgrade reminder and exits 1 as
`SecurityFatalError`. The installed framework permits an identical normal retry;
those separate retries exit 0. No skip flag, upgrade preference, dependency pin,
security rule or branch changes. The failed build attempts remain failed.

The [official advisory](https://github.com/vercel/next.js/security/advisories/GHSA-rhh4-g77r-r9qj)
identifies a Moderate cache-disclosure/poisoning issue affecting versions through
16.4.4 and patched in 16.4.5. This source does not declare `use cache` or
`cacheComponents`; that observation does not resolve every published advisory or
establish absence of runtime exposure. Successful compilation does not clear the
dependency limitation. A dependency-patch decision remains separate from this
bounded correction and from distribution rights.

## Native coverage preservation prerequisites

The new operator first exposes unavailable file-descriptor inspection for three
unrelated session processes; it does not claim those processes are absent. A
proposed C-symbol VFS identification then fails because this qualified Python has
builtin SQLite. Both failed preparations remain retained before any full suite.

The corrected operator qualifies actual default SQLite lock interoperability on
the exact runtime and evidence filesystem: all six small synthetic checks pass.
A held writer prevents copying; a closed writer permits an exact unchanged copy;
new writers are blocked before and after copying while the source fence is held.
Snapshots use one source descriptor, stable identities and hashes, fsync and
explicit sidecar refusal. The proof concerns cooperating writers on the qualified
runtime, not arbitrary VFSes or uninspectable-process absence. No source SQL,
coverage threshold, test selection or security policy changes.

`native-copy-v3-qualification-02/receipt.json` exits 0 in 0.554 seconds;
`native-copy-v3-regression-02/qualification.json` binds the actual six checks,
Python 3.13.15, builtin SQLite 3.53.1, helper hashes and filesystem. The complete
suite and cumulative native coverage remain pending until executed on a frozen
committed candidate. Raw phase inputs and a native combined base must be retained
before reporting, with `combine --keep` and report/JSON/XML `--keep-combined`.

## Correction validation checkpoint

`make format-check lint typecheck generated-check docs-check` passes, exit 0 in
92.167 s, including architecture and the exact ten-GET broker-boundary checks.
The full configured `make sast-check` passes again after the history correction:
exit 0 in 132.280 s, seven rules, 996 files and zero findings. Both executions
preserve working-source manifest
`e9c475217bf06fcf8ffc2bc47266c80094536272bf81ecfd89b7382207c1d370`
at parent `9ffe93452a86155b24b7945698981a56e2c8d696`. Receipts are
`account-history-complete-static-01/receipt.json` and
`account-history-full-configured-sast-02/receipt.json`. Later status-only metadata
records these actual results; no aggregate test or acceptance pass is inferred.

## Remaining qualification

A current-source paired build comparison, focused Python prerequisite checks,
one complete compatible native coverage attempt, security closure and complete
traceability reconciliation remain pending
in this continuing package. Historical scanner, browser, coverage and build
failures remain visible. No complete current-SHA validation pass is claimed.

The retained build comparison includes generated private framework keys,
expiration clocks, action identities and real execution traces. A safe correction
cannot make private keys predictable or exclude substantive artifacts. Any change
to that artifact contract requires a separate owner decision. A historical failed
pair is not current-source qualification.
