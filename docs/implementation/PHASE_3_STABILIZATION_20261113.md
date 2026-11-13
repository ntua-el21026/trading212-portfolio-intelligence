# Phase 3 stabilization checkpoint — 13 November 2026

Status: investigation and validation in progress; no package or release accepted.

## Scope and source

The owner authorized baseline recovery, dependency and build remediation,
contract/browser regressions, and the interrupted P3-08 aggregation vertical.
The assignment excludes new features, remaining Phase 3 feature packages,
Phase 4, production deployment, Live access, release tags and 1.0.0 acceptance.

Starting local and fetched remote `main` were
`64e2057cb9b1ddee11649f605e968b18bd559fcb`, tree
`d4ca30e22e09496c27913456e528d740f4895e21`. The working tree was clean.
GitHub repository metadata identified public visibility. The proprietary
[license](../../LICENSE.md) remains unchanged.

The [September checkpoint](PHASE_3_RESUME_20260930.md) remains a historical
record. Its external operator paths and unfinished staged feature work are not
clean-clone prerequisites and are not incorporated by this stabilization task.

## Reproduced baseline

| Observation | Source and disposition |
| --- | --- |
| Documentation, workspace, Ruff, architecture, broker boundary and generated contracts | Passed at the unchanged starting tree. The adapter still exposes exactly ten GET capabilities. |
| Historical/scenario contract subset | Three failures and four passes at the unchanged starting tree. The accepted aggregation and saved FX read add five paths and seven operations; current canonical generation matches committed artifacts. Historical descriptor and client compatibility require explicit checks of these additions. |
| Original aggregation selector | Reproduced PostgreSQL `aggregate native component proof differs` before its expiry assertion. |
| Native-component diagnosis | Synthetic SQL diagnostics show components inserted before input memberships. Native IDs, values, currencies, snapshot associations, quality and provenance match; membership is absent at the trigger check. SQLAlchemy does not infer trigger-only dependencies. |
| Python dependency audit | Fresh pip-audit 2.10.1 reports 64 advisory records across five packages. This exceeds the 62 records in the cited historical CI run. |
| Node dependency audit | Fresh production audit reports five high and three critical findings, plus moderate/low findings. Remediation and rescanning remain in progress. |

The cited quality and security Actions runs used
`3bbb212aa8742ccc7e2f3bf83d6af42694682714`, an ancestor of the starting source.
Their logs establish historical failures, not results for the stabilization tree.
No workflow is enabled, disabled, retried or weakened by this task.

## Implemented corrections and component evidence

Publication now flushes snapshot membership before native/FX dependants, admitted
FX before converted components, and root activity digests before guarded activity
payloads. These boundaries remain inside the original transaction, with deadline
checks and final authorization/sealing. Provenance, capacity accounting and
rollback remain enforced.

A separate transfer failure came from casting canonical tagged source JSON as
bare scalars. Forward migration `20261113_0034` follows actual head
`20260915_0030` and replaces five source-side casts with strict finite Decimal
and UTC instant decoders. It adds no table, column or index and rewrites no source
record. The original guard comparisons remain intact. Revision `0030` remains
85,363 bytes with SHA-256
`e0a925d63d92a066f116eccd909fb1714fefaff5aea1aa6d74cb1078ec95c3be`.
Reserved handoffs `0031`–`0033` remain unintegrated; future authorized integration
must follow the actual ledger. Populated downgrade is denied.

New PostgreSQL regressions verify source identity/provenance, forged native and
transfer proof rejection, complete copied-row/capacity/command rollback, current
ownership, restart/replay, strict encoding and populated forward-upgrade source
preservation. Newly created aggregation fixtures use actual UTC rather than an
expired August application clock; historical X-ray facts and database clocks
remain unchanged.

Contract tests name exactly the seven accepted additions while retaining the
original schema/client fingerprints. Browser corrections scope semantic locators
and give widget test hosts real viewport metadata; width, focus, overflow,
keyboard and exact-value assertions remain. Production widgets are unchanged.
The historical synchronization timeout has not reproduced; its five-second
assertion is unchanged and its CI root cause remains unverified.

The MCP 2.2 compatibility configuration explicitly retains the existing shared
JWT audience-verification boundary. Nine signed RS256/ES256/EdDSA transport
cases accept the configured audience and reject substituted resource/foreign
audiences. SDK warnings become test errors; no warning is suppressed.

The following are actual precommit working-tree observations. Their full file
manifests bind the tested composition; they do not qualify the unchanged starting
HEAD or constitute an immutable release pass. Failed predecessors remain retained.

| Command or scope | Observed result |
| --- | --- |
| Full formatting, lint, strict typing, documentation and generated-contract checks | Passed; mypy inspected 1,134 files before the subsequent SDK test addition. |
| `pytest tests/unit tests/property tests/contract tests/security` | 5,386 passed, no failures/skips; 107 warnings before the explicit SDK configuration correction. |
| Focused signed JWT/MCP follow-up | 343 passed with no warnings, including nine new cases; Ruff and strict typing passed. |
| `pnpm test:unit` | 918 passed across 103 files. |
| Aggregation, migration, custody and saved-FX PostgreSQL subset | 27 passed; zero failures, errors or skips. |
| Full demo Playwright suite | 196 passed; the subsequent stricter scoped credential-visibility assertion passed both viewport cases. |
| Targeted browser regressions | 18 passed after retained selector/viewport failure proofs. These overlap the full demo suite. |
| Python 3.13.15 runtime requirements / production Node audits | Zero known vulnerabilities / zero findings at every severity. |
| Six runtime image builds and probes | Passed; application UID 10001, PostgreSQL/Redis UID 999; package-manager rejection and retained dpkg metadata verified. |
| Six immutable-ID Trivy vulnerability/secret scans | Zero configured HIGH/CRITICAL findings with available fixes and zero secrets; existing `ignore-unfixed` policy retained. |
| Complete 1,920-file candidate source export | Configured Trivy vulnerability, secret, configuration and license gates passed. |
| Git history / existing secret policy | Zero Gitleaks findings after 38 individually verified fingerprint exceptions; 16 approved-line and 21 negative policy cases passed. Two adjacent-line canaries also remained detected. |
| Host production build and artifact checks | Passed; runtime-only secret and export-URL canaries absent from all five declared artifact paths. |

The additional unfiltered working-directory scan failed three license
classifications in ignored installed third-party files (psycopg notices and a
ReportLab font notice). That distinct result is retained. No license file or
scanner gate was removed; public binary redistribution remains unauthorized.

The first immutable-source `make validate` attempt failed as recorded below. A
new complete target and API-backed production browser qualification remain pending.

## First immutable gate and retention fixture recovery

The first complete target ran at committed `cac650324ef9f74557400fa31199b8d8f59feac8`,
tree `68856b88e7743aa16ffe9464a5f4f7b16bf87ede`. Formatting, lint, strict typing,
4,744 Python unit tests, 918 web unit tests, 36 property tests and 357 contract
tests passed. The integration invocation selected 730 cases; it was interrupted
after two failures and 108 passes to collect the failure tracebacks. The target
failed, its source manifest was unchanged, and later stages were not reached.
Its failed receipt and log remain retained rather than being combined with
subsequent component checks into a complete pass.

The two enrichment failures expected two completed purges from 32 inspections.
Accepted ADR-0032 physical accounting reserves 64 inspections for one payload
mutation, before scheduling and marker/progress/completion costs. Related source
fairness fixtures had the same obsolete expectation. Their expiry ordering also
did not establish the UUID order used by the physical scan. The corrected tests
retain a separate 32-inspection no-removal probe, verify actual payload equality,
and use 257 explicitly ordered busy sources per family against a 256-inspection
allowance. Committed resumes must preserve bounded row/byte work and durable
progress, complete the free owner's exact events while the busy owner remains
locked, and then drain all blocked sources with unchanged identities and hashes.
Production retention code, guards, costs and ceilings are unchanged.

The source partial-purge fixture assumed its one permitted removal must remove
an observation. SQL tracing instead showed one charged deletion of projection
sweep metadata. The corrected fixture retains the one-removal allowance and
requires bounded committed progress until exactly one target observation is
removed, followed by the original parent, completion and replay assertions.

A risk-copy fixture required a downstream marker after a zero-removal source call,
which correctly returns before copy participants. Its zero-removal probe now
checks unchanged canonical bytes, normalized rows and expiry events. A separate
two-removal probe reaches the pending risk marker after the original-source and
historical-copy projection sweep deletions. Direct database queries verify that
the original source observations and canonical risk bytes remain intact; the
original financial-drain and capacity assertions still run. An initial new
one-removal probe could not cross those two metadata removals; that failed attempt
and both diagnostic parser versions remain retained.

The empty-head migration test still expected revision `0029`, despite the
aggregation and decoding migrations. An actual red execution confirmed head
`0034` after repeated upgrade and metadata parity. Only the explicit current-head
expectation changes; historical revision checks and SQL migrations are preserved.

The task stack now uses the documented free loopback ports 5432/6379 because some
legacy fixtures use them directly. Its images and disposable task volume are
identical across the port remap; the earlier high-port configuration remains in
its original evidence. These corrections are test-only follow-ups. The complete
target must be rerun against a new clean committed checkpoint before claiming
complete local validation.

The following actual focused follow-ups passed after their retained red attempts:

| Scope | Observed result |
| --- | --- |
| Strengthened enrichment fairness and full blocked-source drain | Two cases passed in 141.13 seconds; the owned test and production bytes were stable during the run. |
| Complete source dispatch/retention file | Seven cases passed in 346.15 seconds with an unchanged complete source manifest. |
| Empty/repeated current head and ORM parity | One case passed in 3.92 seconds. |
| Zero-removal and source/risk copy boundary | One case passed twice with observational SQL tracing; latest 28.60 seconds, unchanged source manifest. |

## Reproducible synthetic validation

Use the pinned Python, uv, Node and pnpm versions in the repository version files
and manifests. Bootstrap from the repository itself; no broker credentials,
private archive or historical operator environment is required:

```bash
make bootstrap
make docs-check lint-python architecture-check generated-check
uv run pytest tests/contract/test_historical_contract.py tests/contract/test_scenario_contract.py
```

For database-backed tests, use one task-owned Compose project and a disposable
synthetic database. Set a local-only password consistently for Compose and the
test connection, and bind published services to loopback. Preserve unrelated
volumes and never use global pruning. The repository's current gates are exposed
through `make validate`; successful invocation must be recorded before claiming
that gate passed.

Initial focused SQL checks used the exact pinned PostgreSQL 18.6 upstream image.
Subsequent integration and fixture follow-ups use the built hardened task image
with the same disposable task volume and per-test databases. Image builds and
vulnerability scans retain their separate receipts. Both pre-existing local
database volumes are preserved.

## Evidence and acceptance boundary

Actual command receipts retain the command, UTC start, duration, exit code,
source manifest, HEAD/tree, log hash and source-change indicator. Failed attempts
are retained separately from retries. The baseline environment is Python
3.13.15, uv 0.12.7, Node 24.20.0 and pnpm 10.34.5 on WSL2, with Docker Desktop
29.9.3 and Compose 5.7.0. The initially installed uv 0.12.9 is retained; an
isolated pinned uv invocation supplies 0.12.7 without replacing the existing
project environment.

All 30 [acceptance rows](PHASE_3_ACCEPTANCE_MATRIX.md) and all 48
[scenarios](PHASE_3_SCENARIO_EVIDENCE.md) remain pending. Implemented, locally
validated, independently reviewed, accepted and production-authorized states
remain distinct. The final candidate and independent audit remain pending.

Provider credentials, licensed account access, production identity/secret-manager
selection, hosted MCP/ChatGPT registration and production restore/signing remain
separate external prerequisites. GitHub Actions retains its owner-deferred policy;
historical retrieved runs do not constitute current CI validation.
