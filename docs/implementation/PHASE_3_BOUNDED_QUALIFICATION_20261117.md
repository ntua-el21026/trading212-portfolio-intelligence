# Phase 3 bounded Checkpoint B qualification, 17 November 2026

**Owner:** Michail Athanasios Peppas  
**State:** Bounded package closed with failures; Checkpoint B incomplete; independent acceptance pending.

## Authority and source

The initial verified live, local and remote-tracking `main` baseline was
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
Python 3.13.15, builtin SQLite 3.53.1, helper hashes and filesystem. The complete suites subsequently execute at the candidate below. Their failed
outcomes and the separately qualified cumulative native coverage remain distinct.
Raw phase inputs and a native combined base are retained before reporting, with
`combine --keep` and report/JSON/XML `--keep-combined`.

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

## Complete implementation-candidate qualification

The clean, synchronized implementation candidate is
`55bf78ddc258bac0ae9c17abd2db672212bba78d`, tree
`469c19b5980682a1547866f917e048740c578fa5`. Source bookends preserve manifest
`b00fc0f6b9927518da66ff994249d7d1ac3d3708960976ed9c958aa27d40f03f`.
The later documentation delivery is a separate SHA; unchanged implementation
bytes do not constitute another complete execution. Python 3.13.15, Node 24.20.0,
pnpm 10.34.5 and uv 0.12.7 remain qualified. Original dependencies and CPU/database
settings are preserved. Expensive operations run serially.

| Gate / actual command scope | Result | Actual outcome and receipt |
| --- | --- | --- |
| `coverage run -m pytest tests/unit tests/property tests/contract tests/security` | FAIL | 6,005 pass, 1 fail, zero errors/skips; exit 1; 2,378.503 s; `python-full-01-isolated/receipt.json` |
| `coverage run -m pytest -m 'migrations or integration'` | FAIL | 960 pass, 2 fail, zero errors/skips; exit 1; 15,086.414 s; `python-full-01-integration/receipt.json` |
| `corepack pnpm test:unit` | PASS | 966 tests in 109 files; exit 0; 11.884 s; `typescript-complete-candidate-01/receipt.json` |
| Native `coverage combine --keep`, report, JSON and XML `--keep-combined` | PASS, scoped | Actual exits 0/0/0/0; unchanged 70% branch-aware threshold: 88.05021452407436%; separate metadata postvalidation 0 |
| Clean Python/Node install, workspace, Python/Web build and verification | PASS | All eight component operations exit 0; new private environment; `clean-current-*-01/receipt.json` and `clean-install-01/` |
| Paired complete artifact comparison | FAIL | Both builds exit 0; comparison exits 1; 277 Web differences, zero Python differences; `paired-current-v2-compare-01/receipt.json` |
| Six current-candidate images and runtime package-manager probes | PASS, scoped | Actual exits 0/0; 17.724 / 1.826 s; `candidate55bf-six-image-build-01` / `candidate55bf-runtime-package-managers-01` |
| Production Python dependency audit | PASS | pip-audit 2.10.1; 67 active packages, zero skips/vulnerabilities; actual audit 0; `candidate-dependency-python-audit-01` |
| Production Node dependency audit | PASS at configured threshold | Actual audit 0 at HIGH threshold; one Moderate remains; `candidate-dependency-node-audit-01` |
| Full configured Trivy source scan | PASS scanner; operator failures retained | Two actual scanner exits 0; two adapter/operator exits 2; existing-observation metadata postvalidation 0; details below |
| New backup/restore and nine-service restart | PENDING_LOCAL | Backup prerequisite exits 1 before any dump or restore; two Redis keys are preserved; dependent transition/restart not executed |
| Complete current API/browser, LCP and four-format browser matrix | PENDING_LOCAL | Local pre-capture privacy prerequisite is unresolved; three focused Back passes remain separate |
| Current complete `make validate` | PENDING_LOCAL | Not repeated: the complete Python commands already fail and the aggregate would repeat unchanged suites; historical aggregate FAIL remains FAIL |
| Final delivery source/history security and GitHub metadata | PENDING_LOCAL at this commit | Execute after documentation freeze; exact post-commit receipts and actual outcomes accompany the private final delivery |

All exact argv, environment observations, durations, exits, raw logs, JUnit and
before/after manifests are retained privately. The [78-item supplement](PHASE_3_BOUNDED_TRACEABILITY_20261117.md)
binds 49 actual execution records. Neither this matrix nor the supplement combines
separate runs into a full-suite pass.

### Python failures and independent coverage

The isolated failure is
`test_repository_contains_no_high_confidence_secret`; the checker reports three
path/rule messages. The integration failures are
`test_acquired_fx_complete_chain_preserves_authority_and_four_format_proof`
(`storage_unavailable` during completion) and
`test_measured_research_read_query_and_report_admission_budgets` (admission p95
4.034860579 s under coverage). The latter completes all ten genuine jobs and
thirty reads; read p95 is 0.357222205 s and maximum SQL count is 12. Covered timings
are not another bare qualifying cohort. The earlier bare admission failure and
unresolved attribution remain unchanged.

The original full controller then exits 2 because its reporting metadata and data
directories collide, before any combine command starts. A separate reporting-only
recovery runs combine/report/JSON/XML successfully, but its validator exits 2 on
a legitimate Coverage 7.16 display field. The final metadata-only postvalidation
passes: all 14 producer fields, 622 per-file records, counter identities, XML,
source proofs, receipts, sealed native base and original inputs agree. Statements
are 76,433/83,507 (91.52885386853796%); branches 17,764/23,474
(75.675215131635%). Both failed suite exits and both earlier operator exits remain.
No tests or successful coverage commands are repeated for these reporting fixes.

One opted-in focused storage diagnostic passes in 83.641 s without reproducing
the original failure. A single read-only scalar query takes 0.001935 s and observes
valid job/input/fence/lease predicates; the DB clock is about 33.94 s beyond the
fixture clock, still inside the unchanged 60-second lease. No original SQL error
occurs. A bounded earlier PostgreSQL-log classification finds a public stale-fence
reason in a conservative time window, without exact job correlation. This supports
a hypothesis, not a verified cause. The original storage failure remains unresolved;
no fixture/production clock, heartbeat, timeout or assertion is changed. Focused
native data is retained separately and never merged into complete-suite coverage.

### Independent byte boundaries and recovery cases

All 22 PostgreSQL X-ray canonical-payload migration cases pass, as do the 12 core
migration cases and the other selected populated-upgrade/compatibility cases.
Published revision `0036` is unchanged; there is no new migration. Exact encoded
X-ray 32-MiB input/result, oversized rejection, unaffected kinds and safe downgrade
contracts retain their own executed tests.

Both actual report calibration/boundary cases pass. The real near-boundary
capture measures **33,508,884 bytes**, 45,548 below its 33,554,432-byte document
cap, with 52 chunks, a 66,657-byte manifest and maximum chunk 1,047,537 bytes.
Oversized admission rejects at `document_bytes` with unchanged persistent state;
foreign manifest access precedes private-payload selection. The legal document's
complete rows exceed the independent 10,485,760-byte artifact cap, so its genuine
worker correctly terminates `LIMIT_EXCEEDED` without artifact publication. This
is successful boundary enforcement, not a successful oversized artifact export.
The executed boundary observation lasts 350.486 s and preserves both sources.
No X-ray, document, manifest, chunk, artifact or 512-MiB projection limit changes.

Complete-suite modeled recovery/restore tests retain individual results in the
supplement. A new nine-service observation is not inferred from them. All 17
metadata guard regressions pass, and image/tag/original-volume protection passes.
The actual new backup helper nevertheless refuses before dumping or creating a
restore database: Redis DB0 contains two keys. A read-only diagnostic checks all
16 database counts, fixed resource identity, disabled persistence and idle clients;
it reads no key names or values. Nothing is flushed, deleted or recreated.
The task Redis remains running and its PostgreSQL volume remains preserved.
Current restart, restored financial witness and signed artifact pack therefore
remain locally pending. This is a data-preservation prerequisite, not an external
credential blocker. Historical synthetic restart/RTO observations remain historical.

### Complete artifact comparison and safe limits

Both builds use the same exact source/export, verified installed dependency
copies, tools and controlled environment. All four original artifact roots remain
in the comparison. Of 277 Web differences, 239 are common-file content differences
and 38 are membership differences; there are zero type/mode changes. Another
3,377 mtime differences are recorded separately. Build ID, preview material,
server-action mapping, encryption material and trace bytes differ. No private
field value or individual key hash is emitted. Python artifacts match.

The initial private preparation fails on a missing `json` import before building.
Its evidence remains; a separate derivative fixes only that import and uses fresh
namespaces. It produces the actual failing pair. No files are excluded, no bytes
normalized and no crypto inputs made predictable. Defining another artifact
contract or key lifecycle requires an owner decision; the existing whole-tree
repeatability requirement remains failed.

Clean install/build is an independent component pass, not repeatability. Six
current images build and pass runtime package-manager checks while all earlier
image IDs/tag bindings and original-volume metadata remain intact. Tracked source
bookends do not prove exclusive Docker-context membership: filename/type review
finds no present private-input candidates, but `.dockerignore` and ignored local
patterns are not identical. No private input is read or new ignore policy added.

### Trivy metadata recovery and final security boundary

The first actual full configured scan exits 0 with a fresh supported vulnerability
DB and no reported findings; its adapter exits 2 on a legitimate aggregate target.
The pinned public [Trivy producer](https://github.com/aquasecurity/trivy/blob/e1fd17a0ea4a8cf24bc4b4dd7e2cfbf4bb31b994/pkg/scan/local/service.go#L360-L383)
emits exactly `Loose File License(s)`, class `license-file`, without Type. A narrow
private adapter recognizes only that tuple; eight metadata regressions preserve
all rows, findings and per-license path denials. Rules, severity, targets and
license policy are unchanged.

The one full configured repeat also exits 0, with a fresh DB and zero findings,
and recognizes that exact tuple. Its enclosing operator exits 2 because a final
metadata-wording edit overlaps execution. A subsequent metadata-only check
reconstructs the exact recorded executed-source hash from that one known edit,
verifies existing command/source/export/tool/DB/receipt facts and exits 0. It makes
no scanner request and does not rewrite either previous operator failure. Its
reconstructed source is explicitly distinguished from an originally retained
file. Original and recovery evidence remain separately indexed.

Fresh delivery-SHA SAST, high-confidence, source/reachable-history Gitleaks and
independent findings review follow the documentation commit. Their actual exits
and classifications belong to the private post-commit closure record; historical
nonsecret classifications never convert scanner failures into passes. Workflow
status is read only; CI activation remains owner-deferred. License wording and
third-party obligations are unchanged. Public source visibility supplies no
additional dependency, binary or container distribution rights. The existing
[license wording proposal](../verification/LICENSE-VISIBILITY-WORDING-PROPOSAL.md)
requires owner review.

## Preservation, remaining work and disposition

The original 593-entry host Next output and original `next-env.d.ts` and
`tsconfig.tsbuildinfo` are restored after listener checks, with exact byte/type/
mode verification. Every task build is retained privately. Existing `.venv`,
dependencies, images, two original volumes and all previous archives are preserved.
The two task Redis keys prevent cleanup that could lose unique state. Resource inspection reads no process arguments, real-account credentials, signed
URLs or private account input payloads. Authenticated local fixtures use synthetic
accounts; existing tools handle Git/GitHub transport authentication. The exact ten-GET default-deny broker boundary and financial contracts
remain intact; UI draft documents, published migrations, workflows and licensing
rights are unchanged.

The smallest next actions are bounded ownership/retention classification of the
two Redis keys before restart/restore; closing browser capture before the full
matrix; reproducing the original storage failure with causal evidence; owner
review of the whole-tree artifact contract; and owner-directed next steps for the
failed admission requirement and remaining security/dependency decisions. No
further admission-specific cohort or speculative optimization is performed here.

All 30 rows and 48 scenarios remain pending, zero accepted. The indexed private
archive and post-commit closure supply final delivery SHA, exact security/CI
observations, inventory and checksum without a self-referential recommit loop.
No complete final-SHA validation, formal acceptance, Phase 3 completion, P3-10,
production, external-provider or distribution claim is made.

**CHECKPOINT B INCOMPLETE — NOT READY FOR ACCEPTANCE.**
