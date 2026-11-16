# Phase 3 final Checkpoint B local qualification, 16 November 2026

**Owner:** Michail Athanasios Peppas. **Status:** Local qualification executed
with material unresolved failures; private post-commit closure pending.
Checkpoint B remains incomplete. All 30 acceptance rows and 48 scenarios
remain pending, zero accepted. Formal P3-10 has not started.

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
The subsequent complete-suite executions and their retained failures are recorded below.

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

## Current browser qualification and bounded correction

The complete clean-`7c2828a` production API browser execution retains 75 spec/viewport cells, 128 passing tests and ten failures, exit 1 in 4050.594 seconds. Zero skips, flakes or global errors are reported. Four projection failures begin keyboard checks while the new account route is still loading. Explicit positive heading and account-scoped readiness checks preserve every negative assertion, timeout and 55+55 keyboard traversal. All six affected projection cells pass separately in `api-projection-browser-readiness-01` (401.626 seconds, working manifest `ace3e0726291fe3ef100e5de6a79888382390bbf11998c7fb9dade387325f8e8`).

A bounded passive lifecycle diagnostic verifies native form restoration on a new back-forward document, with matching secondary URL/HTML selection/financial markers but primary live select values. The routing `AccountSelect` disables autocomplete; account authorization, masking and document navigation remain intact. Native history passes on all three viewports. Delayed tests now hold the exact main document or the same-origin service worker's actual fetch. Real native keyboard input supersedes the held response on all viewports. Back still fails `ERR_ABORTED` on all three before post-Back account and late-response predicates. Its product/browser/harness cause remains unresolved; the diagnostic loop stopped without changing those assertions.

The later clean-`b89eea3` current-code performance execution `account-routing-browser-performance-02` passes in 783.884 seconds. Each viewport retains five holdings and five research samples. Research LCP p75 is desktop/tablet/mobile 2336/2360/2332 ms against 2500 ms; maximum interaction is 24 ms, CLS is 0 and counted application JavaScript is 63137 bytes. All original samples and thresholds remain. The separate `current-code-research-report-browser-02` passes three genuine PDF/CSV/XLSX/JSON generation, manifest/download and denial journeys in 361.498 seconds. Subsequent worker-only source changes do not alter their frontend inputs; these observations are not whole-source executions at the later SHA.

The configured legacy desktop/mobile Demo matrix passes all 196 cases in 206.010 seconds. It changes only generated `next-env.d.ts`; `legacy-generated-source-restoration-03` restores the exact committed bytes afterward. That recovery does not retrospectively turn the browser execution into an immutable-source pass. The original failed aggregate and every intermediate failure remain separate.

## Worker health deadline correction

The first clean-`b89eea3` six-image build succeeds in 631.302 seconds. The original restart preflight fails before service mutation because its synthetic DATABASE_URL was omitted. The corrected run fails the unchanged 600-second exercise limit and its separate 120-second cleanup, total 720.928 seconds. Those failures remain retained.

Docker probe observations and one bounded unchanged-image diagnostic show a genuine pong at 4.073 seconds, but original CLI completion at 10.124 seconds. Installed Kombu source explains five seconds collecting additional replies; the remaining post-pong time is unpartitioned. A diagnostic reference using the same application, timeout 5 and limit 1 completes in 3.400 seconds. These are diagnostic observations, not substituted recovery evidence.

The internal probe now imports the unchanged real Celery application, collects one structured pong and fails silently on missing/invalid responses or exceptions. Consumer configuration, task registration, financial code and permissions remain unchanged. Docker's 30 s interval, 8 s timeout, 15 s start period and three retries remain fixed. This preserves an any-responsive-worker liveness predicate; it does not certify a specific container, database readiness or job completion.

Ten new response/privacy cases pass under focused coverage in 15.508 seconds; the module's 12 measured statements and four branches are 100% covered. This module-only data is copied and verified before reporting. Two existing configuration cases passed in a separate earlier ten-case invocation. No global coverage result is manufactured from these scopes.

At clean `1497a1df908ad2ea1f471c469ce0c9fd26e8a6cb`, the six new qualification images build in 975.900 seconds and runtime package-manager checks pass in 4.188 seconds. `nine-service-health-qualification-03` passes exit 0 in 74.938 seconds, with measured synthetic recovery of 51.234597695 seconds. Its indexed artifacts retain exact source/image/resource identities, durable projection boundary, canonical fingerprints and duplicate-transport checks. It supplies this driver's scoped recovery proof, not all-family or production RTO certification. Prior qualified images and failed execution evidence remain distinct.

## Clean installation and repeatability

Isolated clean Python and Node installation, workspace verification, Python package builds and Web build execute at the frozen `7c2828a` source. The original project environment, installed dependencies and caches are preserved; task runtimes remain separate. These observations precede the later routing and health changes and are not relabeled final-SHA installation evidence.

Both original and repeated build outputs are preserved. The actual `clean-repeat-compare-01` exits 1 in 12.275 seconds: Python has zero content/type/mode differences, while Web has 271. Separately, 3378 filesystem mtime changes are observed. The record does not attribute the 271 differences solely to timestamps or exclude differing files. Successful individual builds do not establish byte reproducibility.

Original production-source coverage is 87.86518954798298%, above 70%, with line 91.36115935085934% and branch 75.42820622070728%. Its qualified production inputs are byte/mode equivalent, while the underlying complete test executions retain failures and separate sources. Reporting consumed earlier native parallel inputs. Original JSON/XML and receipts remain; focused-only recombination separately fails at 45.7647127%. The new health module's 100% measurement is a separate module-only observation. Complete cumulative native coverage has not been regenerated; no expensive full-suite rerun is performed to hide this limitation.

## Current security and artifact qualification

At clean application candidate `1497a1d`, the frozen production Python audit passes. The Node audit exits 0 under its configured threshold, reporting zero high/critical and one moderate vulnerability. A fresh database-backed Trivy filesystem execution exits 0 in 724.135 seconds; six qualification-image scans also exit 0. Their HIGH,CRITICAL severity filter and ignore-unfixed policy remain unchanged. These results do not establish zero vulnerabilities at all severities or dependency/binary/container redistribution rights.

Configured SAST ultimately discovers all 996 expected target paths under seven configured rules with zero rule findings. It still exits 3 in 17.026 seconds, retaining one code 3 warning for `apps/web/tests/research-report-actions.test.ts`. Its underlying error-type object is withheld and the cause is unresolved; no production parse defect is inferred. Two earlier protocol failures remain. The separate changed-source scan passes, but does not override the full configured gate. No rule, suppression or policy is weakened.

The local artifact bundle passes source/SBOM/image/provenance/signature qualification in 35.706 seconds. One positive verification and two negative integrity checks (actual CLI exits 0/1/1) are retained by the passing integrity wrapper. The ephemeral public key SHA-256 is `95fe61e1abcfe1efd5f3cd8c13d70670dbc8744342d7d1959356ad0103453cb2`; no private signing key is retained. This is private synthetic/local artifact evidence, not production signing attestation or distribution authorization.

Retained predecessor Gitleaks source/history scans report nonzero exits; their 56/2 findings were classified nonsecret at their historical sources. A classification does not change the actual scanner exit. Fresh exact final-commit source and reachable-history attempt 2 runs occur after this documentation freeze. Their actual SHA, source manifests, reports, exits, counts and classifications are supplied in indexed private `post-commit-closure.json` and the final handoff. This document does not predict those outcomes or claim final-SHA scanner success. `LICENSE.md` and third-party obligations remain unchanged; public GitHub visibility is distinct from proprietary ownership and distribution rights.

## Qualification and acceptance

**C. CHECKPOINT B INCOMPLETE — MATERIAL UNRESOLVED FAILURES.** Admission latency has no verified production cause, pending-navigation Back has no established product/browser/harness cause, Web artifact repeatability fails and complete cumulative native coverage is unavailable. Configured SAST also retains its nonzero exit and unresolved warning. Each gate below records its actual source-qualified observation; passing focused scopes are not combined into a complete current-SHA pass.

All **30 acceptance rows** and **48 scenarios** remain formally pending, **zero accepted**. The [complete traceability record](PHASE_3_FINAL_LOCAL_TRACEABILITY_20261116.md) maps every requirement to code, tests, execution/source evidence and remaining action. Synthetic restore/restart results do not certify production RTO/RPO. P3-10 has not started. CI activation, real providers, production/Live, licensing and distribution remain separately gated. Final committed-source scanner and evidence-archive closure is supplied privately after documentation freeze; no public count or success is predicted.

Exact disposable cleanup completes separately: two positively identified synthetic Redis keys are retained as opaque DUMPs with expiry metadata and readback verification before WATCH-guarded deletion; no queue payload is removed. The subsequent guarded retirement passes in 19.919 seconds and removes only the task's nine containers, owned volume and owned network. Original two volumes, nine qualified images, five preceding archives, the original environment and dependencies remain protected. All twelve task qualification-tag bindings retain their recorded image IDs. Final metadata binding passes in 4.692 seconds after the original metadata-only selector failure; no JUnit case or guard is removed.

| Gate | Observed state | Evidence | Qualification |
|---|---|---|---|
| Original aggregate make validate | FAIL | local-make-validate-01/receipt.json, strict-python-type-recovery-02/receipt.json | The complete invocation at `6e4810` fails strict typing, exit 2 in 31.707 s. The specific typing correction passes separately; the aggregate target was not repeated or relabeled. |
| Complete isolated Python execution | FAIL | coverage-python-isolated-all-01/receipt.json, report-v3-auth-mock-recovery-01/receipt.json | At `8f6b775`:5,984 pass/12 fail, exit 1 in 1128.869 s. Eleven stale report Session doubles and one unchanged high-confidence source-secret assertion are retained;13 affected authorization cases pass separately after the fixture correction. |
| Complete service-backed Python execution | FAIL | coverage-python-integration-all-01/receipt.json, coverage-integration-focused-recovery-01/receipt.json, coverage-shared-evidence-recovery-02/receipt.json | At `cdab340`:880 pass/10 fail/72 setup errors, exit 1 in 13173.685 s. The affected recovery has80 pass/1 fail, followed by a separate one-case pass. No fictional complete-suite recovery is constructed. |
| TypeScript component suites and affected checks | PASS | typescript-unit-all-01/receipt.json, typescript-typecheck-01/receipt.json, account-routing-unit-01/receipt.json, account-routing-final-web-types-01/receipt.json | The complete8f6b775 component execution passes961 tests in 109 files. Changed account-routing components and strict web typing pass separately; later worker-health changes do not alter frontend inputs. |
| Scoped static, architecture and generated-contract checks | PASS | generated-contracts-01/receipt.json, worker-health-static-recovery-03/receipt.json, worker-health-architecture-check-03/receipt.json, account-routing-final-format-01/receipt.json | Generated contracts pass at `8f6b775`; the final health source has focused lint/strict typing/architecture recovery and account/browser files retain formatting checks. These source-qualified component checks do not replace failed aggregate Make. |
| Executed migration/upgrade/downgrade subsets | PASS | coverage-python-integration-all-01/receipt.json, coverage-integration-focused-recovery-01/receipt.json, coverage-shared-evidence-recovery-02/receipt.json | The original failed full integration run independently contains48passing migration cases, including22 X-ray canonical payload migration cases. Scenario-schema/fixture recoveries remain separate. Published migrations are unchanged; this is scoped evidence, not a green full PostgreSQL suite. |
| Original production-source coverage measurement | PASS | coverage-report-01/receipt.json, coverage-json-01/receipt.json, coverage-xml-01/receipt.json | Original combined coverage87.86518954798298% passes70%; line 91.36115935085934%, branch 75.42820622070728%. Production inputs were byte/mode equivalent; underlying full test executions retain failures and separate sources. |
| Cumulative native coverage data | PENDING_LOCAL | coverage-report-recoveries-02/receipt.json, worker-health-coverage-report-03/receipt.json | Reporting consumed the earlier native parallel files. Retained JSON/XML and receipts preserve the original measurement; focused-only recombination fails 45.7647127%. New health-module100% is separate module-only evidence. A complete cumulative native dataset has not been regenerated. |
| Report admission latency | FAIL | admission-original-control-01/receipt.json, admission-external-passive-02/receipt.json | The final bare control at `6a5fb4bc` fails p95/max0.832402193 s against 0.750 s; ten jobs and30 reads complete, read p95 0.341415128 s and maximum 12 statements pass. Passive diagnostic admission 1.007202906 s is a separate failure. Cause unresolved; bounded investigation stopped. |
| Original complete API browser matrix | FAIL | api-browser-matrix-01/receipt.json | One complete clean `7c2828a` 75-cell execution retains128 passing tests/10 failures, no skips/flakes/global errors, exit 1 in 4050.594 s. Separate later recoveries do not turn it into a complete passing matrix. |
| Focused projection browser readiness | PASS | api-projection-browser-readiness-01/receipt.json | All 6 projection/projection-report viewport cells pass separately in 401.626 s on exact unchanged working manifest `ace3e072...`, after positive new-account route-readiness assertions. Original privacy negatives and55+55 keyboard steps remain. |
| Current-code three-viewport browser performance | PASS | account-routing-browser-performance-02/receipt.json | At clean `b89eea3`, all 3 current-app protocols pass with 5 samples per route: research LCP p75 desktop/tablet/mobile2336/2360/2332 ms against 2500; interactions at most24 ms, CLS 0, application JS 63137 B. Later health-module/Docker changes have no affected frontend inputs. |
| Current-code four-format research report journeys | PASS | current-code-research-report-browser-02/receipt.json | Three genuine desktop/tablet/mobile journeys at clean `b89eea3` pass in 361.498 s, covering selected immutable sources, real PDF/CSV/XLSX/JSON generation, manifest/download and access-denial behavior. No historical build substituted. |
| Legacy Demo browser execution | PASS | demo-browser-matrix-01/receipt.json, legacy-generated-source-restoration-03/receipt.json | All 196 actual cases pass on the configured desktop/mobile projects. The run changes only generated next-env.d.ts; exact restoration is subsequent and does not retrospectively make the run immutable-source. |
| Back under a genuinely held account document | FAIL | account-routing-workspace-bare-held-recovery-05/receipt.json, account-routing-workspace-tablet-qualification-06/receipt.json, account-routing-workspace-mobile-qualification-06/receipt.json | Back fails ERR_ABORTED on all 3 viewports before required post-Back account/late-response proof. Native account history and real-keyboard supersession pass separately. Product/browser/harness cause remains unresolved; the bounded diagnostic loop stopped. |
| Scoped synthetic restart and retained restore/recovery evidence | PASS | nine-service-health-qualification-03/receipt.json, coverage-python-integration-all-01/receipt.json | At clean `1497a1d`, nine-service restart passes exit 0 in 74.938 s; measured recovery51.234597695 s, exact resource/canonical and duplicate-transport predicates retained. Original integration separately contains passing operational/process/family/restore-restriction cases. The nine-service run is not proof of every modeled family or production RTO. |
| Isolated clean install and local build executions | PASS | clean-python-install-01/receipt.json, clean-node-install-01/receipt.json, clean-python-build-01/receipt.json, clean-web-build-01/receipt.json, clean-verify-01/receipt.json | Frozen-source `7c2828a` isolated installs and Python/Web builds pass without changing the original environment. These sources precede later routing/health corrections; no complete current `1497` clean-install pass or byte reproducibility is inferred. |
| Web artifact byte repeatability | FAIL | clean-repeat-compare-01/receipt.json, clean-repeat-first-inventory-01/receipt.json, clean-repeat-repeat-01/receipt.json | The actual paired `7c2828a` comparison fails:271 Web content/type/mode differences,0 Python differences;3,378 mtime changes separately observed. Both outputs are preserved. No exclusions, timestamp-only explanation or current-SHA repeatability pass is invented. |
| Current-source six-image build and runtime controls | PASS | qualification-health-six-image-build-02/receipt.json, qualification-health-runtime-package-manager-check-02/receipt.json, qualification-health-stack-readiness-02/receipt.json | All 6 unique private qualification images build at clean `1497a1d` in 975.900 s; runtime package-manager checks and the initial seven-long-running/two-one-shot service state pass. Original qualified tags/images are separate and retained; no distribution right is granted. |
| Full configured SAST | FAIL | candidate-security-01-configured-sast/receipt.json, candidate-security-configured-sast-diagnostic-02/receipt.json, candidate-security-configured-sast-project-root-03/receipt.json | Final configured scan discovers all996 expected target paths under 7 configured rules and0 rule findings, but scanner/command exit 3 with one code 3 warning at research-report-actions.test.ts. Underlying error-type object is withheld; cause unresolved. Two earlier protocol failures remain; zero findings do not imply a passing scanner. |
| Retained predecessor Gitleaks exits and owner disposition | OWNER_DECISION_REQUIRED | Separate prerequisite | Historical source 56/history 2 findings were classified nonsecret in retained independently reviewed records; scanner exits remain 1. These are not fresh1497 executions. Existing source/history reports remain in prior evidence archives; no fabricated current receipt is assigned. |
| Exact final-commit source/history scanner closure | PENDING_LOCAL | post-commit-closure.json | After final documentation commit, actual source/history attempt 2 reports, exits, finding counts, classifications and final Git/source identities are recorded in indexed private post-commit-closure.json. Public documentation does not predict these outcomes. |
| Exact disposable resource retirement | PASS | final-owned-stack-backup-retirement-04/receipt.json, retire-exact-known-recovery-result-05/receipt.json, final-owned-stack-backup-retirement-05/receipt.json | After the retained safe retirement 04 failure, exact cleanup 05 passes in 2.043 s: two known synthetic Redis keys are DUMP/fsync/readback-preserved before per-database WATCH deletion; no queue payload is deleted. Guarded retirement 05 passes in 19.919 s, removing only nine exact task containers, one owned task volume and one owned task network. Original resources and all twelve qualification-tag image bindings are retained. |
| GitHub Actions policy and final-SHA observation | OWNER_DECISION_REQUIRED | Separate prerequisite | Keep all 3workflows owner-deferred and disabled. Final source server/workflow/run observation belongs to the post-commit closure; no CI activation or success is claimed. |
| Licensing, visibility wording and redistribution | OWNER_DECISION_REQUIRED | Separate prerequisite | LICENSE.md and third-party obligations are unchanged. Existing public-visibility wording proposal awaits owner decision. Source publication is distinct from rights to distribute dependencies, signed binaries or container images. |
| Credentialed providers and production prerequisites | BLOCKED_EXTERNAL | Separate prerequisite | Real Trading212/provider verification, paid activation, hosted OAuth/MCP/ChatGPT registration and production ownership/credentials require external owner prerequisites outside this authorization. Synthetic local unfinished work is not reclassified as external. |
| Private local artifact bundle and negative integrity cases | PASS | candidate-local-artifact-evidence-01/receipt.json, candidate-local-artifact-negative-integrity-01/receipt.json | Local source/SBOM/image/provenance/signature bundle qualifies at `1497a1d` in 35.706 s. One positive verification and two negative integrity checks (actual CLI exits 0/1/1) are preserved by the passing 1.138 s integrity wrapper. Ephemeral public key95fe61e1... is bound; no private signing key is retained, no production attestation/publication/distribution right is claimed. |
| Frozen production Python dependency audit | PASS | candidate-security-01-requirements/receipt.json, candidate-security-01-python-audit/receipt.json | Actual frozen production requirements export and isolated Python audit pass at `1497a1d`. Preserve exact tool/report/environment bindings; do not expand this to unexecuted dependencies or redistribution rights. |
| Node dependency audit at configured severity | PASS | candidate-security-01-node-audit/receipt.json | Actual Node audit exits0 at `1497a1d` under the unchanged configured threshold.0 high/critical findings;1 moderate finding remains in reported counts. Do not claim zero vulnerabilities at all severities. |
| Configured filesystem vulnerability/security scan | PASS | candidate-security-01-trivy-fs/receipt.json | Fresh database scan exits0 in 724.135 s with0 filtered Vulnerabilities/Secrets/Misconfigurations/Licenses across 10 sections. HIGH,CRITICAL and ignore-unfixed policies are unchanged; this is neither an all-severity guarantee nor a license-rights decision. |
| postgres qualification-image scan | PASS | candidate-security-01-trivy-image-postgres/receipt.json | Actual1497a1d qualification-image scan exits0 at the configured HIGH,CRITICAL threshold with unchanged ignore-unfixed policy. Exact source/image/report binding is retained; no all-severity or distribution authorization claim. |
| redis qualification-image scan | PASS | candidate-security-01-trivy-image-redis/receipt.json | Actual1497a1d qualification-image scan exits0 at the configured HIGH,CRITICAL threshold with unchanged ignore-unfixed policy. Exact source/image/report binding is retained; no all-severity or distribution authorization claim. |
| api qualification-image scan | PASS | candidate-security-01-trivy-image-api/receipt.json | Actual1497a1d qualification-image scan exits0 at the configured HIGH,CRITICAL threshold with unchanged ignore-unfixed policy. Exact source/image/report binding is retained; no all-severity or distribution authorization claim. |
| worker qualification-image scan | PASS | candidate-security-01-trivy-image-worker/receipt.json | Actual1497a1d qualification-image scan exits0 at the configured HIGH,CRITICAL threshold with unchanged ignore-unfixed policy. Exact source/image/report binding is retained; no all-severity or distribution authorization claim. |
| mcp qualification-image scan | PASS | candidate-security-01-trivy-image-mcp/receipt.json | Actual1497a1d qualification-image scan exits0 at the configured HIGH,CRITICAL threshold with unchanged ignore-unfixed policy. Exact source/image/report binding is retained; no all-severity or distribution authorization claim. |
| web qualification-image scan | PASS | candidate-security-01-trivy-image-web/receipt.json | Actual1497a1d qualification-image scan exits0 at the configured HIGH,CRITICAL threshold with unchanged ignore-unfixed policy. Exact source/image/report binding is retained; no all-severity or distribution authorization claim. |
| Changed-source SAST subset | PASS | candidate-security-01-changed-sast/receipt.json | Actual changed-source SAST subset passes exit 0 in 6.814 s. This narrow observation does not override the configured-scope exit 3 failure. |
| Final all78 metadata binding | PASS | final-traceability-binding-01/receipt.json, final-traceability-binding-recovery-02/receipt.json | The original 0.445 s metadata-only overlong-selector failure is retained. Corrected binder 02 passes exit 0 in 4.692 s using bounded parameter-hash display for long JUnit selectors; source JUnit is unchanged, no case is dropped and no bound is raised. The complete public traceability contains exactly 30 acceptance rows and 48 scenarios, all formally pending. |
| Final indexed archive and private post-commit closure | PENDING_LOCAL | post-commit-closure.json | Seal only after final source/history scans and closed evidence. The reviewed operator includes every regular evidence file, verifies all execution receipts/bookends/logs and stream-verifies members; actual archive path/size/checksum come from its future completed seal, not this documentation draft. |
