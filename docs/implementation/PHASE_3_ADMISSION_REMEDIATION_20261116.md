# Phase 3 Checkpoint B admission diagnosis and remediation, 16 November 2026

**Owner:** Michail Athanasios Peppas. **Disposition: Admission remediation FAILED.**
The original uninstrumented admission gate still fails; broad and reduced
observers do not establish a production cause or justify an optimization. Checkpoint B
remains incomplete. All 30 acceptance rows and 48 scenarios remain pending, zero
accepted. Formal P3-10 has not started.

## Authority and source qualification

Read-only preflight verified clean synchronized local/origin/live GitHub main
`8adf4806528fc186a0778c9d08d71d636fe1b562`, tree
`a81009f4b85534c4c75f36398def707a77a998cb`. This assignment authorizes focused diagnosis and evidence-supported remediation.
Complete qualification, P3-10, new migrations, external activation and changes to
financial, broker, security or licensing contracts remain outside this package.

The uninstrumented baseline, broad diagnostic and reduced-observer confirmation
all execute at that clean SHA with
unchanged complete source manifest
`dbaf6fc96c7cb09b4d679b516a20247c7b41439d6d7530ac0bded01a1847b4f6`.
No production code, tests or migrations changed in this assignment. The original
fixture, assertions, limits and nearest-rank percentile method remain unchanged.
Later documentation-only commits do not create new performance executions.

## Environment and workload

Actual test records report CPython **3.13.15**, Linux
`6.18.33.2-microsoft-standard-WSL2`, x86_64, glibc 2.43 and 24 logical CPUs. The
separate inventory/control helper reports Python **3.14.4**; that is its own
interpreter, not the project test runtime. These observations must not be merged
into a fictitious single-interpreter environment. uv 0.12.7, Node 24.20.0 and
pnpm 10.34.5 are retained tooling. UV_NO_SYNC=1 preserves the existing .venv and
installed dependencies. No package installation or clean-install qualification is
inferred. One newly named disposable PostgreSQL service uses the retained qualified
image with pull/build disabled; Redis is not started.

The original service-port protocol uses one ordinary untimed research read, 30 timed
current reads and ten timed report admissions, each followed by genuine untimed
worker execution and successful status verification. Independent financial/source
assertions execute outside each read interval. Timing starts before report-selection
and command construction and ends after the awaited service returns. Admission
p95 is the largest of ten observations. Required bounds remain admission ≤0.750 s,
read p95 ≤0.500 s and at most 12 SQL statements per current read. No sample is excluded.

## Uninstrumented baseline

Receipt `admission-uninstrumented-baseline-01` exits **1** after **99.622 seconds**.
All ten jobs complete. Admission p50 is 0.561338604 s; p95/max is
**0.779183911 s**, with ordinals 1 and 4 above 0.750 s. Thirty reads pass at
p95 **0.324819180 s**, p50 **0.111065490 s**, and maximum SQL count 12. This confirms
that the starting implementation still fails the admission requirement; it does not
establish any benefit from prior codec/scalar changes.

The [15 November consolidated record](PHASE_3_CHECKPOINT_B_CONSOLIDATED_20261115.md)
retains the preceding source-qualified historical failures: 0.772447935 s, 0.789630626 s and 0.856597051 s. They are not merged with this
baseline or with instrumented observations.

## Diagnostic method and limitations

Private opt-in plugin `admission_diagnostic` observes the exact existing test rather
than replacing it. It returns the original monotonic clock values unchanged and
records all 80 calls: 60 for 30 reads and 20 for ten admission boundaries. All ten total
wall samples reconcile exactly with the original harness. Fixed application and
ORM/driver callables receive nested inclusive/exclusive wall and thread-CPU spans;
main-thread command work and worker dispatch/execution are recorded separately.
SQL observation retains categories/counts/durations only. Natural GC callbacks
record generation, wall/CPU and fixed enclosing phase. Start/end live allocated
blocks, GC counters and resource deltas are net/proxy observations, not a total
allocation count or memory peak. Worker schedstat/resource deltas and sampled
PostgreSQL wait classes provide bounded scheduling/lock evidence.

No SQL text/parameters, credentials, private payloads, account IDs, backend PIDs,
URLs or exception messages are persisted by the diagnostic. No forced collection,
GC-policy change, synthetic warmup, cProfile, tracemalloc or cache bypass is used.
Restoration reports zero conflicts and the PostgreSQL sampler stops.

**Broad tracing materially perturbs execution.** Its current-read p50 is
0.278712385 s versus baseline 0.111065490 s, and read p95 is 0.568664065 s. The broad
admission p95/max is 1.981961946 s. Those values are diagnostic observations,
not qualification or a measured production regression. Synthetic empty-wrapper/
clock/cursor calibration is only a lower-level observer check: it cannot model the
real graph/GC/environment effect or justify subtracting overhead from real samples.

Inclusive phases overlap; SQL, GC, scheduler and transaction observations also
overlap those phases. They must not be added to produce a false latency budget.
Driver cursor spans omit commit and some ORM work; these have their own enclosing
boundaries. Guest scheduler/pressure/steal counters do not prove external host
contention or GIL waiting. Sampled absence of blockers does not rule out shorter
unobserved waits. All timing retains observer overhead without correction.

## Fast versus slow broad-diagnostic observations

The slowest broad admission is ordinal 1, 1.981961946 s; the fastest is ordinal 10,
1.299970434 s. Their observed difference is 0.681991512 s.

| Observation | Slow admission 1, ms | Fast admission 10, ms |
| --- | ---: | ---: |
| Total original timed call | 1981.961946 | 1299.970434 |
| Process CPU | 1390.678534 | 1054.005105 |
| Worker CPU | 1349.700568 | 1026.942135 |
| Worker wall | 1979.513922 | 1298.413522 |
| SQL driver wall | 532.029812 | 366.179448 |
| SQL driver CPU | 122.242348 | 117.559330 |
| Outside worker wall | 2.448024 | 1.556912 |
| Thread dispatch wall | 0.106626 | 0.104940 |
| Natural GC wall | 311.397622 | 29.709888 |
| Natural GC CPU | 310.350878 | 29.399945 |
| Generation-2 GC wall | 269.557123 | 0.000000 |
| Worker runqueue wait | 1.852393 | 0.241662 |

There are 678 versus 677 observed SQL executions; the first new report definition has
an additional insert/flush. Both observations contain 15 advisory-lock calls, whose
aggregate spans are 4.952661 ms and 5.350302 ms. Maximum sampled blocker count is 0.
The slow admission has 38 natural GC cycles versus 26; its generation-2 cycle
occupies 269.557123 ms within input decoding. Broad ordinals 4 and 7 contain
386.556349/381.658188-ms cycles in different phases. These observed overlaps do
not establish a production defect or avoidable allocation.

The driver commit boundary is 210.942162 ms versus 17.172348 ms; it is distinct from
SQL execute-event totals but nested within transaction/worker wall. The broad
trace therefore contains significant GC, SQL/commit and residual variation; a
single production bottleneck or a speculative optimization target is not established.

| Measured boundary | Calls, slow / fast | Slow admission 1, inclusive ms | Fast admission 10, inclusive ms |
| --- | ---: | ---: | ---: |
| Selection validation | 1 / 1 | 0.661070 | 0.147592 |
| Command validation | 1 / 1 | 0.154908 | 0.036157 |
| Command digest, including encoding | 1 / 1 | 0.186227 | 0.209756 |
| Initial request authorization | 1 / 1 | 5.831409 | 6.266586 |
| Repeated authorization checks | 37 / 37 | 118.925898 | 123.968105 |
| Research metadata/source entitlement | 7 / 7 | 433.996266 | 361.407710 |
| Physical source permission checks | 42 / 42 | 64.310124 | 49.659392 |
| Canonical X-ray input decoding | 1 / 1 | 284.766027 | 28.732866 |
| Canonical X-ray result decoding | 1 / 1 | 67.011929 | 76.316644 |
| Canonical X-ray result encoding | 1 / 1 | 21.558574 | 25.471092 |
| Report table construction | 20 / 20 | 189.492024 | 192.550812 |
| Report chunk encoding | 20 / 20 | 17.432105 | 19.450542 |
| Manifest construction/encoding | 2 / 2 | 43.158882 | 32.260759 |
| Input sink sealing/retention/provenance | 1 / 1 | 369.934844 | 220.145438 |
| Source retention deadline | 1 / 1 | 25.227323 | 17.817303 |
| Dependency projection | 1 / 1 | 61.818658 | 49.447639 |
| ORM scalar, including its driver calls | 393 / 393 | 344.463342 | 309.990496 |
| ORM execute, including its driver calls | 181 / 181 | 256.054466 | 198.469297 |
| ORM scalars, including its driver calls | 70 / 70 | 70.140268 | 57.868688 |
| ORM flush, including its driver calls | 29 / 28 | 176.545484 | 55.170548 |
| Transaction commit, including nested commits | 30 / 29 | 214.407112 | 19.121554 |
| Driver commit boundary | 1 / 1 | 210.942162 | 17.172348 |

These are inclusive wall spans, deliberately not summed. Complete exclusive/inclusive
wall and CPU values for every phase of every admission are retained in
`diagnostic-phase-table-01.csv`; `diagnostic-numeric-analysis-01.json` provides the
separate CPU/SQL/non-CPU arithmetic decomposition and its causal limitations.
Allocation deltas are −15,085 versus +13,527 live blocks, not total allocation volumes.
Worker voluntary/involuntary context switches are 885/6 versus 825/2; no causally
identified host scheduler explanation follows from them.

## Complete executed sample inventory

| Ordinal | Uninstrumented baseline, s | Broad diagnostic, s | Reduced observer, s |
| ---: | ---: | ---: | ---: |
| 1 | 0.764744687 | 1.981961946 | 1.747281868 |
| 2 | 0.607914392 | 1.469840799 | 1.408030441 |
| 3 | 0.561338604 | 1.374550025 | 1.660759978 |
| 4 | 0.779183911 | 1.793289792 | 1.205045472 |
| 5 | 0.546465677 | 1.795534409 | 1.254096749 |
| 6 | 0.545979555 | 1.489833807 | 1.675036298 |
| 7 | 0.541432928 | 1.739304688 | 1.157829998 |
| 8 | 0.563858506 | 1.343276959 | 1.328181346 |
| 9 | 0.560525555 | 1.372496537 | 1.657514982 |
| 10 | 0.568140268 | 1.299970434 | 1.060107183 |

Each cohort completes ten real jobs. Both diagnostic exits preserve the original
threshold assertions; neither is an uninstrumented qualifying cohort. Original
failed outputs and all slow samples remain retained.

## Reduced-observer confirmation and stop decision

Receipt `admission-reduced-observer-confirmation-01` exits **1** after
**207.059 wrapper seconds / 203.85 test seconds** at the same clean source.
All ten jobs complete and all ten total intervals match the original harness
exactly. Admission p50 is **1.328181346 s**, p95/max **1.747281868 s**;
read p50 is **0.265772173 s**, p95 **0.499726265 s**, with maximum SQL count 12.
These remain instrumented observations, not qualifying SLO results.

This confirmation removes function-phase aliases, ORM session wrappers, per-query
trace allocation, the sampler thread, extra database connection and wait queries.
Only the exact admission-clock, worker-dispatch, SQL aggregate, natural-GC and
driver-commit boundaries remain. PostgreSQL wait sampling is **unmeasured**, not
zero. GC callbacks are restored and restoration conflicts are zero. The complete
macro-stage measurements for all ten admissions are:

| Ordinal | Worker CPU, ms | SQL wall, ms | Driver commit, ms | GC wall, ms | Gen-2 GC, ms |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1109.533007 | 557.980477 | 198.838168 | 39.830968 | 0.000000 |
| 2 | 968.554800 | 486.688965 | 67.804384 | 26.723316 | 0.000000 |
| 3 | 1304.253702 | 434.040107 | 36.018548 | 344.827892 | 320.546485 |
| 4 | 953.012378 | 354.175294 | 5.844858 | 22.554519 | 0.000000 |
| 5 | 968.712511 | 391.199044 | 4.453891 | 35.373805 | 0.000000 |
| 6 | 1370.957727 | 383.562071 | 32.547157 | 407.813747 | 382.941156 |
| 7 | 896.899358 | 349.008871 | 13.285174 | 30.185075 | 0.000000 |
| 8 | 1007.924432 | 392.611508 | 39.024967 | 27.927692 | 0.000000 |
| 9 | 1369.798228 | 396.523766 | 6.010449 | 409.688595 | 383.493037 |
| 10 | 832.504480 | 316.081409 | 5.290328 | 31.351545 | 0.000000 |

These columns overlap and must not be summed. All process/main/worker CPU, SQL
category counts/timing, driver-commit CPU, allocation proxies, context switches
and runqueue values are retained in `report-lite-phase-table-01.csv`, derived
without a new execution from `admission-diagnostic-lite-01.json`.

The slowest reduced observation is ordinal 1, **1.747281868 s**; the fastest is
ordinal 10, **1.060107183 s**. Both contain 15 advisory-lock calls. The first has
678 SQL executions versus 677 for the last, including the ordinary first-definition
insert. Driver commit is **198.838168 ms** versus **5.290328 ms**. A disjoint
arithmetic partition, without assigning unproven causes, is:

| Arithmetic partition | Slow reduced admission 1, ms | Fast reduced admission 10, ms |
| --- | ---: | ---: |
| Worker CPU | 1109.533007 | 832.504480 |
| SQL wall minus its thread CPU | 435.808252 | 218.591786 |
| Driver commit wall minus its thread CPU | 198.585602 | 5.206950 |
| Other worker non-CPU residual | 0.395668 | 2.028760 |
| Outside worker wall | 2.959339 | 1.775207 |

Natural generation-2 collections occur at ordinals 3, 6 and 9 for
**320.546485 / 382.941156 / 383.493037 ms**; they are overlays within worker CPU
and wall time. Ordinal 1, the slowest reduced admission, has no generation-2
collection. The broad trace's generation-2 locations therefore do not establish
the cause of the original uninstrumented slow admissions. Allocation counters
remain net live-block proxies. GC thresholds and enabled state were unchanged;
the observed collection timing belongs to this instrumented execution.

The reduced observer still produces substantially larger wall and CPU values than
the uninstrumented baseline. Removing the broad phase wrappers and sampler does
not explain that macro-level inflation. Neither the small synthetic observer
calibration nor guest scheduling counters identify its cause. No WSL/host fault,
production GC defect, dominant avoidable source operation or expected optimization
benefit is verified.

**Admission remediation FAILED.** The bounded investigation stops with all three
executions preserved. No production, test, migration, performance-limit or security-
policy correction is justified by the present attribution. No further cohort is
started. The smallest next action is to stabilize and attribute the unexplained
observer/environment/CPU inflation under a separately bounded measurement plan
before selecting any production change. Complete Checkpoint B qualification and
formal P3-10 remain unstarted; this diagnostic failure is unfinished local work,
not an external blocker.

## Exact commands and retained evidence

Actual expanded argv, UTC, exit, source bookends, environment selection and log hashes
reside in the private execution receipts. `$TASK_E` denotes the private task evidence
directory, not a committed machine-specific path.

```bash
uv run pytest -q tests/integration/test_phase3_operational_budgets.py::test_measured_research_read_query_and_report_admission_budgets --maxfail=1

env PYTHONPATH="$TASK_E" uv run pytest -q -p admission_diagnostic tests/integration/test_phase3_operational_budgets.py::test_measured_research_read_query_and_report_admission_budgets --maxfail=1

env PYTHONPATH="$TASK_E" uv run pytest -q -p admission_diagnostic_lite tests/integration/test_phase3_operational_budgets.py::test_measured_research_read_query_and_report_admission_budgets --maxfail=1
```

| Evidence | Actual outcome | Source/scope |
| --- | --- | --- |
| `admission-uninstrumented-baseline-01/receipt.json` | Exit 1; 99.622 s; admission fails, 30 reads and ten completions retained | Clean `8adf480`; complete source unchanged |
| `baseline-qualified-failure-01.json` | Derived inventory of exact original baseline, no new execution | Same raw source; digest/log provenance retained |
| `admission-instrumented-diagnostic-01/receipt.json` | Exit 1; 213.731 s; observer-perturbed diagnostic | Clean `8adf480`; complete source unchanged |
| `admission-diagnostic-01.json` | Ten exact reconciled boundary samples and per-phase metadata | Private plugin/selected-source hashes retained |
| `diagnostic-phase-table-01.csv` | Every ordinal/phase inclusive and exclusive wall/CPU | Derived from actual diagnostic, no new execution |
| `diagnostic-numeric-analysis-01.json` | Fast/slow arithmetic and all ten summary rows | Derived observations; not causal attribution |
| `observer-calibration-01.json` | Synthetic observer-only clock/no-op/cursor calibration; no DB/application calls | No SLO qualification or overhead subtraction |
| `admission-reduced-observer-confirmation-01/receipt.json` | Exit 1; 207.059 s; macro-level inflation remains unexplained | Clean `8adf480`; complete source unchanged |
| `admission-diagnostic-lite-01.json`; `report-lite-phase-table-01.csv` | All ten reconciled macro-stage observations, original failures retained | No function-phase or PostgreSQL wait attribution claimed |

## Remaining qualification and permanent boundaries

There is no complete current-SHA validation pass, owner acceptance, CI result,
production readiness or provider verification claimed. Complete local Make/coverage,
final browser matrix, clean-install/build and broad restart/restore/load qualification
remain **pending_local**, not blocked_external. The existing failed scanner exits
and classified historical findings remain unchanged. The focused source checker
also exits 1 in this package: its six documentary matches in three files are
exactly equal to the previously reviewed nonsecret receipt metadata. Classification
leaves zero unresolved matches and preserves the failed scanner status. No complete
Gitleaks/SAST execution or policy change is inferred from this diagnostic.

The exact default-deny ten-GET Trading 212 boundary, Decimal/NUMERIC/currency/UTC,
provenance/quality/retention and REPORT/EXPORT authorization semantics remain.
LICENSE.md, dependency-license/distribution policy, workflows and published migrations
remain outside this assignment's changes. Independent owner review and acceptance,
formal P3-10 authorization, deferred CI, credentialed providers, production/hosted
infrastructure and distribution rights retain their separate gates.
