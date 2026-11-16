# Phase 3 controlled admission environment diagnosis, 16 November 2026

**Owner:** Michail Athanasios Peppas. **Disposition: Admission remediation FAILED — cause unresolved.**
Checkpoint B remains incomplete. All 30 acceptance rows and 48 scenarios remain
pending, zero accepted. Formal P3-10 and complete Checkpoint B qualification have
not started in this package.

## Authority and immutable execution source

Live GitHub/local/origin main and a clean working tree were verified at
`1e86141984470df6ddfc485d2c41cee3113f8511`, tree
`260aea5ea43d477fb713c950ebe14082031f133c`. Every new workload execution retains
that exact source and unchanged complete path/byte/mode manifest
`19718315b104fbf8eaa4940e4d3c8153331c14a8f550d3d4f3d04284ecaf63d9`.
Subsequent documentation-only delivery does not create a new performance execution.
No production code, tests, financial methods, migrations, thresholds, broker
capabilities, security rules or licensing rights changed.

## Retrospective evidence comparison

The [preceding admission report](PHASE_3_ADMISSION_REMEDIATION_20261116.md) and
[Checkpoint B report](PHASE_3_CHECKPOINT_B_CONSOLIDATED_20261115.md) retain original
failures, diagnostics and qualifications. Complete receipts, bookends and raw
samples were read before any new workload was executed.

| Historical observation | Admission p95, seconds | Qualification |
| --- | ---: | --- |
| Earlier checkpoint | 0.772447935 | Failed, own historical source |
| Codec cohort | 0.789630626 | Failed, own manifested source |
| Scalar-dispatch cohort | 0.856597051 | Failed, own manifested source |
| Latest bare baseline at `8adf480` | 0.779183911 | Failed, clean source |
| Broad observer at `8adf480` | 1.981961946 | Diagnostic only |
| Reduced observer at `8adf480` | 1.747281868 | Diagnostic only |

The last three share complete source bytes but were sequential, not bracketed by
a later bare control. Earlier different-source observations cannot establish a
controlled environment effect. The fixture intentionally creates fresh databases,
UUIDs and retained evidence identities. Its semantic financial/source assertions
are stable; input/provenance digests differ. No exact input-byte equality is claimed.

| Dimension | Reliable historical observation | Gap or limitation |
| --- | --- | --- |
| Source | Last three `8adf480` runs share manifest `dbaf6fc9…` | Other complete source snapshots differ |
| Interpreter | Python 3.13.15 in all three workload records | Inventory helper's 3.14.4 is a separate process |
| Platform | WSL 6.18.33.2, glibc 2.43, x86_64, 24 logical CPUs | No timed-worker frequency or thermal record |
| Dependencies | Closure versions: pytest 9.1.1, SQLAlchemy 2.0.52, psycopg 3.3.4, greenlet 3.5.5 | Not independently captured at each historical start; full installed-tree equality unmeasured |
| Invocation | Diagnostics add `PYTHONPATH` override and a plugin | Original flags, backends, import paths and monitoring state missing |
| PostgreSQL | Same retained image and prepared Compose configuration | Effective historical GUCs, connection/prepared-plan state and resource limits missing |
| Fixture | Same original ordering, thresholds, one warm read, 30 reads and ten admissions/completions | Fresh identities and source fingerprints differ |
| Database state | Each fixture migrates/seeds and later drops its own database | Retirement sizes are after deletion, not in-test size/statistics proof |
| Scheduling/memory | Diagnostic guest load and some runqueue/steal counters | No equivalent baseline pressure/swap/cgroup data; host competition unmeasured |
| GC | Diagnostic enabled state and thresholds `[2000,10,10]` | No baseline per-admission GC; observed ordinals change between observers |

Ordinals 1/4 recur in some failed historical cohorts, while the codec cohort is
slow at 4/8/9. Diagnostic generation-2 collections occur at 1/4/7 or 3/6/9.
Those differing-source or perturbed observations do not establish a fixed ordinal cause.
The historical first admission has an ordinary extra definition insert; its
uninstrumented CPU/SQL/commit contribution is not isolated.

## Cheap startup comparison before database workloads

Four fresh processes cross inherited versus overridden `PYTHONPATH` with no plugin
versus verified old-plugin pre-import. No fixture, database request, test body or
old diagnostic hook executes; prior evidence is loaded without writing its cache.
All measured interpreter flags, executable/module hashes, library versions,
Decimal contexts and native backend selections match. Native Decimal and SQLAlchemy
extensions are active; Psycopg uses binary implementation 3.3.4/libpq 180000.
Tracing, profiling and monitoring tools are inactive in these import probes.

These are pure import-state probes, not the original pytest entrypoint or historical
runtime fingerprints. Equality rules out only measured startup differences. The
results do not fill historical gaps or identify a production cause.

## Bounded experimental design and prospective amendment

The original protocol and assertions remain unchanged: one untimed authorized read,
30 timed reads, ten timed admissions and ten genuine untimed completions. Admission
p95 is the maximum of ten under nearest-rank quantiles. Limits remain 0.750 seconds,
0.500 seconds and 12 SQL statements respectively. No sample or slow ordinal is excluded.

The predeclared budget is three full cohorts. The first A0 case loads a common
stdlib/pytest-only plugin in off mode: original timer and GC callbacks are untouched.
A host snapshot occurs before collection/fixtures; heavy runtime/module/fixture
fingerprints and three fixed catalog SELECTs occur only after the original body.
There is no extra application request, fixture traversal, hashing or database read
between fixture setup and the test body. This context still differs from the
historical bare entrypoint and is explicitly qualified.

A0 is already slow without critical-path observation. Before B, the remaining plan
was amended to use the bare original command followed by the unchanged A-context
repeat, rather than adding the proposed timer/GC treatment. The run budget stays
three; the amendment and original plan remain preserved. B's record is derived
from its actual receipt/raw evidence after execution. Missing host/backend/catalog
fields in B are marked unmeasured; no observer execution is synthesized.

| Case | Context | Wrapper seconds | Exit | Admission p50 / p95, seconds | Read p95, seconds | SQL max | Jobs |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: |
| A0 | Common plugin off; no timed observer | 211.917 | 1 | 1.320008204 / **1.709143293** | 0.646613538 | 12 | 10/10 |
| B | Bare original, no plugin or PYTHONPATH override | 108.198 | 1 | 0.571466095 / **1.022774345** | 0.340622338 | 12 | 10/10 |
| A1 | Common plugin off; no timed observer | 102.929 | 1 | 0.585589239 / **1.076423162** | 0.337825586 | 12 | 10/10 |

| Ordinal | A0 off, seconds | B bare, seconds | A1 off, seconds |
| ---: | ---: | ---: | ---: |
| 1 | 1.637088181 | 1.022774345 | 1.076423162 |
| 2 | 1.316163888 | 0.708693804 | 0.639135457 |
| 3 | 1.559091989 | 0.560306257 | 0.647172925 |
| 4 | 1.324717843 | 0.597979699 | 0.574138437 |
| 5 | 1.198932760 | 0.571466095 | 0.619331438 |
| 6 | 1.196605128 | 0.582667604 | 0.585589239 |
| 7 | 1.413125335 | 0.547189325 | 0.538347629 |
| 8 | 1.320008204 | 0.554545033 | 0.552930678 |
| 9 | 1.274082114 | 0.575797276 | 0.652200546 |
| 10 | 1.709143293 | 0.548548498 | 0.548171403 |

All three executions fail admission. A0 also fails read p95; B and A1 pass read
p95 and the SQL cap. B and A1 exceed 750 ms only at ordinal 1; ordinal 4 is within
limit in both. The same A-context source/plugin/off mode returns materially
faster on repetition. Therefore that context alone is insufficient to explain
all inflation. No performance improvement or isolated host/GC/JIT cause is inferred.

## Observer overhead and measured environment

A separate 100-pair alternating-order calibration executes 80 actual clock calls
with and without the proposed bounded timer/process-CPU/GC bookkeeping. Added wall
cost is 40,152–116,631 ns per 80 calls. No application/test/database or forced-GC work
occurs. That timer/GC treatment was not used in the full experiment, and its
calibration is not an explanation of common-context inflation. No overhead is
subtracted from a workload duration.

The common posterior fingerprint work takes 89.330020 ms after A0 and 42.340966 ms
after A1, outside all timed samples. This does not quantify indirect import/heap/cache
or environment effects. The three full cohorts contain no SQL tracing, worker
wrapper, timing patch, sampler thread or added timed-path GC callback.

The qualified PostgreSQL image remains `sha256:f4754af4cac0eeee2528d0029e2ee508e955cc2f60d489b4c4e9462b0009f529`.
Twenty-five before/after settings, container limits and postmaster start time match;
there is no intervening restart or configuration change. Container memory/NanoCPU
values are zero, meaning no explicit container cap, not zero resources or unlimited
host capacity. Docker reports 24 logical CPUs and 25,196,945,408 bytes RAM.

A0/A1 posterior fixture metadata shows 369 public tables, 1,547 indexes and no
invalid/not-ready indexes. Database sizes are 45,430,463 and 45,212,175 bytes.
Post-test metadata matches except database size: PostgreSQL 18.6, shared buffers
128 MB, work memory 4 MB, JIT on at cost 100000, automatic plan cache, synchronous
commit/fsync on and read-committed isolation. These are posterior snapshots, not
initial statistics, actual admission plans or a connection-state trace. Statistics
can lag; fresh UUIDs and physical layouts differ. B has no catalog snapshot.

Visible guest memory remains available, swap usage/counters are zero, and no
cgroup CPU throttling is observed in the captured counters. CPU0 frequency and
thermal telemetry are unavailable. One normal quota syntax was withheld by the
numeric metadata filter, so no complete effective-CPU-quota claim follows. Point
snapshots cannot rule out short pressure, GIL effects or Windows-host competition.
The original bare B has no added runtime/host observer; historical or adjacent
snapshots must not be substituted for its missing fields.

## Root-cause decision and remaining work

**Verified production cause:** none. Verified observations are source/protocol
integrity, matching measured startup dimensions, unchanged measured PostgreSQL
configuration, and the actual timing differences. **Supported inference:** possible
first-use behavior and unrecorded temporal/runtime/database/host variation.
**Unresolved:** actual CPU, SQL/commit and GC contributions to the bare first-admission
delay, and the mechanism behind A0 versus A1 timing. Previous instrumented stage
costs remain diagnostic-only and are not production latency estimates.

No code correction or new regression tests are justified without a causal defect.
No further full cohort is executed after the fixed budget. The smallest next step
is an independently validated passive first-admission process-CPU versus database
commit/wait measurement preserving the bare entrypoint. It must isolate its own
effect before supporting an optimization. This is pending local engineering,
not `blocked_external`.

Complete Make/coverage, clean installation/build, final browser matrix and expanded
restart/restore/resource qualification remain pending. P3-10 requires separate
owner authorization after review; no owner acceptance or CI success is claimed.
Exact ten-GET/default-deny broker, REPORT/EXPORT rights, owner/account checks,
Decimal/NUMERIC/currency/UTC, provenance, retention and rollback semantics remain
byte-preserved. No real account, provider credentials, Live/production or distribution
operation is performed. LICENSE.md and scanner policy remain unchanged.

## Commands and evidence

Actual expanded arguments, UTC, exits, source bookends, logs and checksums are
retained privately. `$TASK_E` is a logical placeholder, not a public machine path.

```bash
# A0 and A1: same context, no timed observer.
env PYTHONPATH="$TASK_E" T212PI_CONTROLLED_OBSERVER=off uv run pytest -q -p controlled_observer tests/integration/test_phase3_operational_budgets.py::test_measured_research_read_query_and_report_admission_budgets --maxfail=1
# B: original bare entrypoint.
uv run pytest -q tests/integration/test_phase3_operational_budgets.py::test_measured_research_read_query_and_report_admission_budgets --maxfail=1
```

Private logical evidence includes `RETROSPECTIVE_ENVIRONMENT_COMPARISON.{md,json}`,
`startup-comparison-01.json`, the four startup cells, original and amended bounded
plans, `minimal-observer-calibration.json`, all three actual execution receipts,
`controlled-{A0,B,A1}.json`, `CONTROLLED_RESULTS.json`, the complete admission CSV,
and before/after PostgreSQL/resource records. Bare B's derived summary identifies
its actual raw file/hash and labels unmeasured plugin metadata explicitly. Focused
documentation/security/commit/resource/archive closure observations retain their
own actual source in the private handoff; no future pass is inferred here.
