# Phase 1 Technical Baseline

**Status:** Accepted  
**Authority:** Phase 1 runtime, framework, and tooling versions  
**Reviewed:** 2026-08-31

This document supersedes older runtime-version examples in README or Phase 1 narrative documents without changing the frozen architecture. P1-01 locks exact patch/minor dependency versions and commits reproducible lockfiles after primary-source compatibility verification.

## 1. Runtime baseline

| Component | Baseline | Rationale |
|---|---|---|
| Python | `3.13.x` | Mature support across the selected asynchronous API, SQL, testing, and Celery ecosystem; avoid depending on partial Python 3.14 support in Phase 1 |
| Node.js | `24.x LTS` | Current LTS baseline for the TypeScript/Next.js workspace |
| pnpm | `10.x` | Current workspace/package-manager generation; exact version pinned through Corepack/package metadata |
| PostgreSQL | `18.x` | Current supported PostgreSQL major; authoritative system of record |
| Redis | `8.x` | Optional coordination/cache/job infrastructure; never authoritative financial storage |

Runtime images and CI must pin supported patch releases, not floating `latest` tags.

## 2. Python stack

- `uv` workspace and committed `uv.lock`.
- FastAPI and Pydantic v2.
- SQLAlchemy 2 and Alembic.
- `psycopg` v3 for PostgreSQL.
- asynchronous `httpx` for Trading 212 reads.
- Celery 5.6 for durable background execution, with explicit task idempotency/checkpoints; Redis may serve as broker/backend locally, while canonical task state/evidence remains in PostgreSQL.
- official MCP Python SDK/current supported FastMCP primitives with Streamable HTTP-compatible remote transport.
- pytest, pytest-asyncio, Hypothesis, Ruff, strict mypy, coverage tooling.

A different job framework requires an accepted ADR because jobs, retries, leases, checkpoints, and operational behavior depend on it.

## 3. TypeScript/web stack

- Next.js current stable release compatible with Node 24 LTS.
- React current stable release supported by that Next.js release.
- strict TypeScript.
- pnpm workspace and committed lockfile.
- generated TypeScript API client from versioned OpenAPI/contracts.
- Vitest and Testing Library for component/unit tests.
- Playwright for browser, responsive, accessibility-smoke, and end-to-end tests.
- a token-based accessible design system; exact component library choice may be made in P1-01/P1-10 and recorded if consequential.

Do not duplicate authoritative financial arithmetic in JavaScript/TypeScript. The browser formats and visualizes canonical backend results.

## 4. Local and CI infrastructure

- Docker Compose for PostgreSQL 18 and optional Redis 8.
- independently runnable API, worker, MCP, and web processes.
- GitHub Actions on every push to `main`.
- reproducible Make targets wrapping `uv`, `pnpm`, Docker, migrations, tests, builds, and validation.
- least-privilege workflow permissions.
- non-root/minimal runtime containers where practical.

## 5. Version-lock protocol

During P1-01 Codex must:

1. verify primary official compatibility documentation;
2. choose exact compatible versions;
3. pin runtime/tool versions using `.python-version`, package metadata/Corepack, and container tags/digests where appropriate;
4. commit `uv.lock` and `pnpm-lock.yaml`;
5. configure dependency update tooling without automatic unsafe major upgrades;
6. document deviations and accepted ADRs;
7. prove a clean-clone bootstrap in CI.

## 6. Dependency policy

- Prefer primary maintained libraries with active security support.
- Avoid unmaintained convenience wrappers around Trading 212 or MCP.
- Isolate external SDKs behind repository-owned ports.
- Pin direct dependencies and lock transitives.
- Run dependency, license, secret, static, and container scans.
- Never weaken the read-only/default-deny boundary to accommodate a library.

## 7. Compatibility gates

The baseline is accepted only when CI proves:

- Python and TypeScript workspaces install from lockfiles;
- all lint/type/test/build gates run on the selected runtimes;
- PostgreSQL migrations run from empty and upgrade paths;
- Redis absence degrades only optional capabilities where documented;
- API, worker, MCP, and web containers start and pass health/smoke checks;
- no floating runtime/dependency tag controls a release build.
