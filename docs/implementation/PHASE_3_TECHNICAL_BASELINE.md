# Phase 3 Technical Baseline

**Status:** Accepted implementation design; local release evidence pending

**Date:** 2026-09-14

**Release target:** 1.0.0

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

## Runtime and dependency policy

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

Use task project `t212pi_stage_a_20260907`; run services and tests serially and
reuse the same necessary PostgreSQL/Redis instances. Full-stack acceptance may
need the existing seven services; ordinary analytical/unit/design work needs none.
Scope cleanup to inspected obsolete task resources. Preserve dependencies, current
images, source and actual evidence; never global-prune or shrink unrelated stores.

Retain sanitized actual command logs, JUnit/node IDs, source/tree hashes, runtimes,
coverage, browser captures, scans, resource inventories and recovery receipts
outside the checkout, with compact source-bound summaries inside it. Evidence
must remain portable and failed attempts retain original labels. GitHub Actions
is deferred_by_owner and unverified, independent of local gate results.
