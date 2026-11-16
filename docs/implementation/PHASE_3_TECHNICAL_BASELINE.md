# Phase 3 Technical Baseline

**Status:** Accepted implementation design; local release evidence pending

**Date:** 2026-09-14

**Release target:** 1.0.0

## Current controlled environment diagnosis, 16 November

The [controlled environment record](PHASE_3_CONTROLLED_ENVIRONMENT_20261116.md) retains three complete original
workload executions at clean main `1e86141984470df6ddfc485d2c41cee3113f8511`.
The bare original command fails admission p95 **1.022774345 s** against **0.750 s**;
read p95 **0.340622338 s**, maximum **12 SQL statements**, and all ten completions pass.
Two off-mode contexts return admission p95 **1.709143293 / 1.076423162 s**.
The same off-mode context does not reproduce the earlier timing level consistently.
First-admission delay is a supported inference; CPU, SQL/commit, GC and host causes
remain unresolved. No production correction is justified, and the three-run budget
is exhausted. Application code, tests, migrations and thresholds remain unchanged.

All **30 acceptance rows** and **48 scenarios** remain pending, **zero accepted**.
Complete Checkpoint B qualification remains **pending_local**; formal P3-10 has not
started. CI, provider credentials, production/Live and distribution remain separate
owner gates. Earlier records below retain their original source qualifications.

## Historical admission diagnosis, preceding 16 November package

The [focused admission record](PHASE_3_ADMISSION_REMEDIATION_20261116.md) starts from clean live/local
main `8adf4806528fc186a0778c9d08d71d636fe1b562`.
**Admission remediation FAILED; Checkpoint B remains incomplete.** The new
uninstrumented 30-read/ten-admission baseline fails p95/max **0.779183911 s**
against **0.750 s**; all ten jobs complete. Read p95 **0.324819180 s** and
maximum **12 SQL statements** pass. Earlier qualifying failures remain historical.

Broad and reduced observers retain every sample and exact source manifests, but
their inflated timings are diagnostic evidence, not qualifying performance.
The unexplained observer/environment/CPU inflation prevents a verified production
cause or justified optimization. No production code, tests or migrations changed;
the bounded investigation stops without another cohort or speculative correction.

All **30 acceptance rows** and **48 scenarios** remain pending, **zero accepted**.
Complete Make/coverage, browser, clean-install/build and expanded recovery/resource
qualification remain **pending_local**, not external blockers. Checkpoint B is not
accepted; formal P3-10 has not started. CI activation, providers/credentials,
production/Live, licensing and distribution retain their separate owner gates.
The 15 November consolidated observations below retain their original sources.

## Historical consolidated Checkpoint B qualification, 15 November

The historical [consolidated qualification record](PHASE_3_CHECKPOINT_B_CONSOLIDATED_20261115.md) follows owner authorization
from clean main `dabd98ff0cb5ff4c954d4465cebc71ea2a9a0267`. Checkpoint B remains
**INCOMPLETE**. Its last genuine 30-read/ten-admission cohort fails admission
p95/max **0.856597051 s** against 0.750 s (p50 0.617076987 s). All ten jobs complete;
read p95 0.344801251 s and all 12-statement counts pass. Its unchanged source
manifest is `3496f8bf9570cbc0152fcd3f4056ae4dbbe4b19531743028a609ed521630e919`,
headed by `250dc7` with manifested working changes, not clean-commit validation.

Forward schema `0036` aligns X-ray's frozen 32-MiB canonical bounds and retains
368 ORM tables. Separate focused observations demonstrate dense projection
heartbeat recovery, 33,508,886-byte report admission with genuine oversized
rollback, and a 2,092-holding retained-X-ray REPORT fallback with DISPLAY,
foreign-owner, expiry and revocation denial. The near-32-MiB JSON job fails
boundedly with no artifact under independent rendering limits; it is not successful
artifact evidence. A later tablet attribution diagnostic is not final browser
qualification. Fresh-build viewport qualification, complete local Make/coverage,
clean installation/build and recovery/resource qualification remain pending.
Focused committed-source regression and security observations are recorded in the
consolidated report; scanner failures retain their actual status.

Complete applicable local Checkpoint B qualification was owner-authorized.
Formal P3-10 has not started; its attempt count remains **0**. All **30 rows** and
**48 scenarios** remain pending, **zero accepted**. CI is owner-deferred/unverified;
production, Live, real credentials, paid providers, release and distribution rights
remain separately unauthorized. Earlier checkpoint results below retain their
historical source and authority.

The material admission failure stops this bounded package before further
performance cohorts or long Make, coverage, complete browser or clean-install
qualification. Those checks remain **pending local**, not externally blocked.
Narrow source-affected regression and security checks have executed at `cb50452`;
the linked report records their exact scope and failed/recovered exits. Complete
qualification remains pending. Formal P3-10 remains unstarted.

## Historical bounded remediation

Current bounded remediation is recorded in the
[Checkpoint B package](PHASE_3_CHECKPOINT_B_20261115.md), following the retained
[Batch 2 record](PHASE_3_BATCH2_20261114.md). Qualifying desktop/mobile browser
performance passes, but tablet research LCP p75 is 2,724 ms against 2,500 ms.
All 15 research pagination journeys complete. This material local failure keeps
Checkpoint B incomplete regardless of later admission or boundary results;
final admission p95/max 0.772447935 s also fails 0.750 s, while read p95
0.314842558 s and all 12-statement counts pass. Actual 32-MiB attempts fail before admission/rollback: the projection source
worker returns FENCED, while X-ray publication exposes a frozen 32-MiB versus
inherited generic 8-MiB schema conflict. Exact SQL attribution is inferred; the
affected local work stops pending owner scope disposition, not external access. Focused risk/scenario
recovery and other regressions remain separate observations. No frozen threshold,
runtime pin, financial contract or licensing right changes. The complete P3-10
stage is expressly excluded from this package. Earlier projection/full-stack/
report/upgrade/RSS evidence retains its scope; final candidate security and
delivery remain pending.

## Observed starting point

Actual clean main and origin/main were
`d2ebdaf96d1b61aacea5c6492824946540f88803`, tree
`0a8598a853b025bb2cd4f8c30e6bef042756ced2`; local branch main only. Runtime
introspection observed Alembic `20260911_0016`, 87 API paths / 95 operations,
25 MCP tools and ten Trading 212 GET capabilities. The preserved Phase 2 ledger
contains ten packages, 29 acceptance rows and 40 scenarios. These are baselines,
not Phase 3 results. [Owner progression](evidence/phase-3-owner-authorization-20260914.json)
accepts corrected f88b019; it does not imply independent full-archive review.

Governance was delivered at `30fe2ede666bff35e3e95173abcf34558a729cc1`, tree
`d9d81a71cca8e146638eac74b5fb62f465b9ed60`. Its immutable local gate passed in
21.009 seconds, including 463 selected tests, strict typing of 605 files,
Ruff, repository/workspace, architecture/broker, secret and Prettier checks.
These scoped results do not implement or validate a premium product package.

## Historical runtime and dependency baseline

The following table records the design-freeze baseline. Current dependency
manifests and frozen locks remain authoritative; this historical table does not
override later source-qualified dependency updates.

| Component | Retained pinned version |
| --- | --- |
| Python / uv | 3.13.15 / 0.12.7 |
| Node / pnpm through Corepack | 24.20.0 / 10.34.5 |
| MCP / PyJWT / cryptography | 2.1.1 / 2.13.0 / 50.0.1 |
| FastAPI / Pydantic | 0.141.1 / 2.13.5 |
| SQLAlchemy / Alembic | 2.0.52 / 1.19.1 |
| PostgreSQL / Redis | 18.6 / 8.10.1, existing hardened digest-pinned images |

Manifests and frozen locks remain authoritative. This freeze needs no broad
SDK/runtime/dependency upgrade. Verify new APIs against installed source and
primary documentation before adopting them. Any necessary dependency is a
separate narrow, pinned and tested change with license/security justification.
Keep uv-managed .venv, existing pnpm lock and Docker Desktop WSL integration.

The [13 November security remediation](../security/DEPENDENCY_REMEDIATION_20261113.md)
records subsequent exact security pins and immutable Debian package snapshots.
The table above retains the original September baseline; the current manifests
and locks contain those documented corrections. Actual compatibility, scanner
and build outcomes belong to the [stabilization record](PHASE_3_STABILIZATION_20261113.md).

## Shared implementation placement

Domain holds immutable validated premium values, definitions, inputs and result
variants. Analytics holds pure Decimal algorithms. Application holds principal-first
services and fixed typed provider/job ports. Persistence holds normalized scoped
records, source capture, immutable publication, transactional outboxes and retention.
Worker executes the fixed tasks through those services. API and MCP adapt strict
contracts; generated TypeScript clients, web and reports project canonical results.
No layer may add a generic provider proxy, JSON analytical escape hatch or broker
write dependency. Reuse existing auth, command identities, leases and cleanup.

New method IDs are risk_v1, stress_v1, projection_v1, goal_analysis_v1,
research_summary_v1 and account_aggregation_v1, each starting at version1.0.0.
They do not alter the existing registry entries or reinterpret historical results.
The premium numeric profile is isolated in ADR-0019. Canonical identity includes
method/schema/numeric version, all financial assumptions, source/cutoff/currency
and seed where applicable; excludes operational IDs, worker/chunk identity and
calculation clock. Current legal access remains separate from immutable identity.

The REST prefix /api/v1 and existing generated OpenAPI filename are compatibility
identifiers, not release labels. Keep current 0.2.0 runtime release metadata until
the deliberate P3-10 synchronized candidate version change. Migration changes form
one linear chain after 0016. Test empty install,0016 upgrade, repeat and genuine
synthetic restore, without destructive historical downgrades.

## Local gates and resource boundaries

Use Makefile's actual entry points and pinned tools. Start with focused tests,
then relevant lint/type/generated-contract/database/browser/build checks. Complete
make validate and documented image/security/restart/restore gates at the final
immutable implementation source. Record line, branch-only and combined coverage
separately and deduplicate isolated/service-backed node IDs.

Use one explicitly selected task Compose project; run services and tests serially
and reuse its necessary PostgreSQL/Redis instances. The historical
`t212pi_stage_a_20260907` project identifies an earlier exercise, not a requirement
to attach new work to its preserved volume. Current Compose defines seven
long-running services (PostgreSQL, Redis, API, worker, dispatcher, MCP and web)
and two one-shot services (migration and synthetic seed). Focused database checks
usually need only PostgreSQL/Redis; ordinary analytical/unit/design work needs none.
Scope cleanup to inspected obsolete task resources. Preserve dependencies, current
images, source and actual evidence; never global-prune or shrink unrelated stores.

Retain sanitized actual command logs, JUnit/node IDs, source/tree hashes, runtimes,
coverage, browser captures, scans, resource inventories and recovery receipts
outside the checkout, with compact source-bound summaries inside it. Evidence
must remain portable and failed attempts retain original labels. GitHub Actions
is deferred_by_owner and unverified, independent of local gate results.
