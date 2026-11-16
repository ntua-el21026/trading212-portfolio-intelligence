# Phase 3 final Checkpoint B local qualification, 16 November 2026

**Owner:** Michail Athanasios Peppas. **Status:** Qualification in progress;
Checkpoint B incomplete. All 30 acceptance rows and 48 scenarios remain pending,
zero accepted. Formal P3-10 has not started.

## Authority and baseline

The owner authorizes one final bounded admission investigation and completion of
independently executable local qualification despite its outcome. Live/local/origin
main was clean at `6a5fb4bc8a65df1c588534d486170ab0535ae226`, tree
`83fc85a9a69d485c351c3186d6b0957b4f449768`. Earlier reports and private evidence
archives remain source-qualified historical observations, not current gate results.
No CI activation, real accounts, provider credentials, Live/production, publication
or distribution-rights decision is authorized.

## Final bounded admission investigation

Exactly two explicit cohorts use unchanged production bytes and original workload:
30 reads, ten admissions and ten genuine completions, nearest-rank quantiles,
0.750-second admission/0.500-second read/12-SQL limits, no exclusions or extra warmup.

| Execution | Admission p95 s | Read p95 s | SQL max | Jobs | Exit |
| --- | ---: | ---: | ---: | ---: | ---: |
| Bare original control | 0.832402193 | 0.341415128 |12|10/10|1|
| External passive diagnostic |1.007202906|0.328699700|12|10/10|1|

The bare control exceeds admission limits at ordinals 1 and 4. The diagnostic retains
only fixed read-only transaction/wait metadata and known-child process counters;
no in-path plugin, monkeypatch, timer change, SQL text/parameters, account payload
or process arguments are recorded. Database transaction brackets exclude preceding
Python work and cannot establish exact whole-admission stage costs. Diagnostic
observations and observer overhead remain separate from qualification. The two-run
budget is exhausted; no verified causal production correction has been selected.
Mandatory original performance tests remain enabled in later aggregate/coverage
runs, with their execution context and results reported separately.

## Exact disposable recovery project

Regression tests first expose four exact-project refusals. The minimal harness
correction admits only `t212pi_batch2_final_checkpoint_b_20261116` to three existing
closed task selectors. Existing authorized project names and historical refusals
remain. Tests preserve near-match/foreign denial before discovery, account-free
resource metadata, exact service/image/network/volume/loopback-port identity and
cross-project plan isolation. No application, broker, financial, migration, resource
threshold or security-policy contract changes.

The first source-patched focused execution retains 106 passing cases and one failed
new test whose shared port-inspection dependency was not doubled. Its focused
recovery fixes that test boundary; original failure and recovery remain distinct.
The upcoming complete suites establish their own counts and outcomes.

## Preserved aggregate failure and strict-typing recovery

The sole `make validate` attempt at clean `6e481021977a99ba14183f0cff79fd1c1492656a`
exits 2 after 31.707 seconds. Formatting, lint, architecture and exact broker checks
pass; strict mypy finds one `union-attr` error in the existing profile3 scenario
manifest test after research joined its binding union. An explicit scenario-type
assertion preserves the exact digest and all negative schema checks while allowing
sound narrowing. All 25 source-affected schema tests pass; the failed strict typing
gate is rerun separately. The aggregate target remains failed, not retrospectively
validated by a later component recovery. Unreached independent gates continue.

## Complete isolated coverage execution and source-affected recovery

At clean `8f6b775fcaf54095bb5509556a454f6c0f070366`, all 5,996 selected unit,
property, contract and security cases execute under coverage. The original run
exits 1: **5,984 passed, 12 failed**, four warnings, 1,128.869 wrapper seconds.
Eleven failures are stale positional Session doubles in profile3 authorization
unit tests: the mandatory normalized research-dependency header lookup now occurs
before ordinary premium authorization. The correction represents its absent row
explicitly rather than bypassing that check. The legacy case now verifies both
metadata-only lookups and the actual research-header entity; all original family,
license, source-restriction and denial assertions remain. All 13 source-affected
cases pass separately, with strict typing/lint/format checks. No production code
changes. The twelfth failure is the existing repository secret-pattern assertion:
three paths/six inherited reviewed nonsecret metadata matches. Its actual scanner
and test failures remain; no rules, excludes or tests are weakened.

This focused recovery does not relabel the original complete execution as passed.
Further service-backed coverage uses its own exact source and receipt; any combined
coverage measure must verify identical measured production files across inputs and
remain separate from a fictitious complete same-SHA test pass.

## Complete service-backed execution and focused corrections

At clean `cdab340fc9f6418c63ec342177540450cf0cf8c7`, all 962 selected integration
and migration cases execute: **880 passed, ten failed, 72 setup errors**, two
warnings, exit 1, 13,173.685 wrapper seconds. The original receipt is
`coverage-python-integration-all-01/receipt.json`; source manifest
`4f4380abd80a3e33bee606ae7c1a05a58800d6e108facedae9da6392c706aa6e` remains unchanged.

All 72 setup errors are connection refusals at port 5432. Three legacy fixtures
ignored the configured isolated server at port 55432: planning (18 affected
cases), sources (30), and virtual targets (24). Both administrative and disposable
database URLs now use the existing configured-URL helper. Alembic's environment
override is scoped and restored; generated names, seeding, repeated upgrades,
schema checks and disposable cleanup remain intact.

Four browser-fixture failures use obsolete server doubles without the required
cleanup event. Their correction retains database isolation, collision and SIGTERM
checks. Three schema failures expect obsolete trigger messages; current messages
and explicit SQLSTATE 23514 preserve the same capacity and retention denials.
The preliminary report calibration uses a frozen operational clock preceding its
real-time worker publication. Its correction follows the existing advancing
report-service clock, retaining financial inputs, source cutoffs and REPORT use.

The shared-evidence test initially fails before its intended header race because
the mandatory owner lock serializes publication and purge earlier. Reusing an
existing provider still acquires that lock through the cleanup-epoch trigger.
The final test therefore proves both owner-lock orderings, logical-copy release
before physical deletion, and post-purge republication denial. SQLSTATE 55P03,
the 200-ms transaction timeout and all ordinary database guards remain.

Only the 81 failed/error cases affected by these corrections are rerun under
coverage: **80 pass, one concurrency case fails**, exit 1, 114.882 seconds,
manifest `3e54b147a50d0d67bd668f1e050bf80a85188b59b2311ce536c6c38cbc18028b`.
The corrected single concurrency case then passes separately, exit 0, 6.542
seconds, manifest `e2007f72557b1b1db73d31465bfe7e69b5d88a8ed1f40852502e22b9a55ec1dd`.
Receipts are `coverage-integration-focused-recovery-01/receipt.json` and
`coverage-shared-evidence-recovery-02/receipt.json`. Original full-suite failures
remain failures. These are manifested working-source observations; no complete
passing committed-source invocation is inferred. Application code, migrations,
authorization, limits and scanner policy are unchanged.

## Coverage measurement and retained operator limitation

The original combined report passes the unchanged 70% threshold: **87.86518955%**
combined, **91.36115935%** lines and **75.42820622%** branches. Its exact counts are
76,282/83,495 lines and 17,703/23,470 branches. `coverage-report-01/receipt.json`
exits 0; original `coverage/coverage.json` and XML remain intact. Production source
equivalence between the component executions is recorded separately from suite
success.

A follow-up operator command starts a new combination containing only the two
focused recovery inputs. Its report, JSON and XML commands exit 2 at
45.76471271%; this is a focused data set, not a production coverage regression.
Coverage 7.16 reporting automatically consumes parallel inputs unless its separate
keep-combined option is supplied. The initial reporting step consumed those raw
SQLite inputs despite the preceding combine command's keep option; their original
JSON/XML reports and execution receipts remain. The follow-up did not append the
original combined data. Both actual command outcomes and this data-retention
limitation remain visible. No complete suite is repeated to reconstruct raw data.
The original cumulative SQLite inputs are unavailable; regenerating a cumulative
native base remains pending local. The preserved native full reports still support
their original measurement. Future accumulation must append explicitly, retain
combined inputs during reporting and snapshot the native base before reporting.

## Current boundary, recovery and resource observations

Within the failed complete integration execution, the genuine near-32-MiB report
test passes separately: **33,508,874 encoded bytes**, 45,558 below its document cap,
52 chunks, maximum chunk 1,047,537 bytes and manifest 66,652 bytes. Oversized
admission reaches the exact `document_bytes` guard and preserves persistent state,
capacity and immutable sources. Its large JSON job remains bounded by independent
artifact limits; no successful near-boundary artifact is claimed. The preliminary
calibration failure and its focused recovery remain separate.

Other actual observations include the 256-MiB retained-capacity rejection boundary,
0036 canonical X-ray byte boundaries, retained-X-ray authorization, dense heartbeat
recovery and modeled-family recovery. Maximum projection work completes in
88.376 seconds with peak worker-tree RSS 348,307,456 bytes, within 240 seconds and
512 MiB. Synthetic backup/restore takes 5.087 seconds; recovery through validated
reads takes 27.082 seconds. A real SIGKILL outage retains canonical chunks and
fencing, with readiness after 6.980 seconds and actual lease redispatch after
61.129 seconds. These scoped observations neither accept a scenario nor certify a
production recovery objective.

## Qualification and acceptance

Aggregate Make, complete suites/coverage, strict static checks, generated contracts,
current-build browser matrix, 0036/populated migration compatibility, synthetic
recovery/restore/resources, clean installation/build and configured security gates
remain in progress until actual execution receipts exist. No combined pass is
inferred from planned commands or partial evidence. Synthetic resilience does not
certify production RTO/RPO. All 30/48 remain formally pending for independent owner
acceptance. CI is owner-deferred; licensing and binary/container distribution rights
remain separate. LICENSE.md and scanner policies are unchanged.
