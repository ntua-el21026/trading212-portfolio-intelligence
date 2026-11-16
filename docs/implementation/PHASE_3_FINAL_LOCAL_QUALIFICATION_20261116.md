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

## Qualification and acceptance

Aggregate Make, complete suites/coverage, strict static checks, generated contracts,
current-build browser matrix, 0036/populated migration compatibility, synthetic
recovery/restore/resources, clean installation/build and configured security gates
remain in progress until actual execution receipts exist. No combined pass is
inferred from planned commands or partial evidence. Synthetic resilience does not
certify production RTO/RPO. All 30/48 remain formally pending for independent owner
acceptance. CI is owner-deferred; licensing and binary/container distribution rights
remain separate. LICENSE.md and scanner policies are unchanged.
