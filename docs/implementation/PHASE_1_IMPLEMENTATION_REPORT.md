# Phase 1 Trusted Foundation Implementation Report

**Release target:** `0.1.0`

**Implementation authority:** `main`

**Base branch/SHA:** `main` at `c566c080762f9d74996e1bdd19d1254848f8f17f`

**Imported Phase 1 SHA:** `7119be95ae41d036f1461dd21bfbf10243c64ab0`

**Corrected final main SHA:** Pending while corrections are in progress

**Acceptance:** Working-tree implementation and all fourteen synthetic scenario evidence
assembled; final release-SHA/CI validation remains pending

**External gates:** Trading 212 Demo and deployed ChatGPT validation are `blocked_external`

## 1. Implemented work packages

| Package | Implemented candidate scope | Acceptance state |
|---|---|---|
| P1-01 | Pinned Python/Node/uv/pnpm workspace, lockfiles, Make interface, CI, formatting, lint, strict types, test layers, builds, generated checks, and scans | Implementation present; final gate pending |
| P1-02 | Exact-decimal values, identifiers, entities, quality/freshness/provenance, canonical serialization, stable application views | Implementation present; final gate pending |
| P1-03 | PostgreSQL models, repositories, seed, Alembic baseline and accounting metadata migrations | Implementation present; final gate pending |
| P1-04 | Demo-default/Live-explicit strict GET-only Trading 212 provider with exact allowlist, typed DTOs, errors, pagination, retry, and redaction | Implementation present; final gate pending |
| P1-05 | Durable runs/checkpoints/leases, idempotent immutable source revisions, mode-aware transaction high-water with seven-day overlap, safe history replay, resumability/coalescing, Celery worker, Redis rate coordination | Implementation present; focused evidence passed; final gate pending |
| P1-06 | Deterministic ledger normalization, reconciliation/discrepancies, quality propagation, immutable snapshot persistence, and API-backed quantity/cash mismatch acceptance path | Working-tree integration/browser evidence passed; final gate pending |
| P1-07 | Exact-decimal portfolio values, direct allocation, income/P&L primitives, explicit sourced FX, external-flow separation, coverage-gated performance | Implementation present; focused evidence passed; final gate pending |
| P1-08 | Sessions, CSRF, authorization, account ownership, token handling, secret-provider port, deployment validation, redaction | Implementation present; final gate pending |
| P1-09 | Typed authenticated `/api/v1`, health/readiness, errors/pagination, OpenAPI, generated TypeScript client, durable refresh queue | Implementation present; final gate pending |
| P1-10 | Responsive authenticated Next.js shell, overview, holdings/detail, allocation, activity, dividends, snapshots, sync, quality, settings, and explicit UI states | API-backed desktop/mobile runtime evidence passed; final gate pending |
| P1-11 | Authenticated Streamable HTTP `/mcp`, nine frozen read-only tools, schemas/annotations, canonical parity, versioned snapshot widget and exact CSP | Implementation present; final gate pending |
| P1-12 | Non-root Dockerfiles, Compose, migrations/seed, health/readiness, observability hooks, Demo smoke, backup/deployment/credential/MCP/troubleshooting runbooks | Working-tree Compose/restart/canary evidence passed; final gate pending |

No Phase 2 or Phase 3 analytical feature is represented as available.

## 2. Important components

- `packages/domain`, `packages/application`, `packages/analytics`, `packages/persistence`: canonical model, use cases, deterministic calculations, and system-of-record adapters.
- `packages/trading212`: the only Trading 212 transport boundary.
- `packages/security`, `packages/observability`: authentication/authorization/secrets/redaction and telemetry primitives.
- `apps/api`, `apps/worker`, `apps/mcp`, `apps/web`: interface and execution composition roots.
- `migrations`: versioned PostgreSQL schema history.
- `packages/api-contracts`: committed OpenAPI and generated TypeScript surface.
- `config/contracts/trading212-read-allowlist.yaml`: frozen machine provider capability registry.
- `scripts/check_trading212_boundary.py`: repository-wide default-deny static gate.
- `compose.yaml`, `infrastructure`, `.github/workflows`: runtime and CI/deployment controls.
- [Operations runbooks](../operations/LOCAL_AND_DEPLOYMENT.md): local/deployment, backup, credentials/Demo, MCP/ChatGPT, and troubleshooting procedures.

## 3. Architecture compliance

The Phase 1 implementation preserves the Design Freeze v0.1 boundaries: PostgreSQL is authoritative; Redis is coordination-only; provider DTOs do not leak into canonical contracts; deterministic code owns financial calculations; API/web/MCP share application services; secrets remain server-side; and the broker adapter is fixed-allowlist GET-only.

All corrections use the accepted direct-`main` workflow. No release-specific alternate
delivery path is active, and no frozen architecture decision changes.

## 4. Trading 212 GET-only enforcement

Defense in depth is implemented through:

1. the exact ten-capability root registry;
2. byte-identical packaged provider registry verification;
3. an HTTP client that constructs only GET requests;
4. pre-transport rejection for `POST`, `PUT`, `PATCH`, `DELETE`, unknown capability, and path injection;
5. closed provider/application capabilities with no arbitrary URL or broker-path input;
6. MCP tools that expose canonical portfolio reads, never provider dispatch;
7. unit, contract, integration, and security negatives;
8. `scripts/check_trading212_boundary.py` in `make lint`, `make test-security`, and CI.

The ten permitted GETs include observational export listing only. Export creation, orders/mutations, Pies, transfers, CFDs, generic proxying, and dormant write clients remain prohibited. Transaction incrementals use the documented `time` lower bound with a persisted seven-day overlap and stable filter validation across cursor pages. Historical orders and dividends have no verified time filter, so they safely replay and deduplicate rather than claiming unsupported incremental semantics.

## 5. Database and migration status

Alembic revisions `20260831_0001`, `20260831_0002`, and `20260831_0003` create
the Phase 1 relational model, complete accounting/reconciliation persistence metadata,
and per-run source-record occurrence membership. Exact numerics, UTC timestamps, keys,
idempotency constraints, immutable source revisions, calculation versions,
reconciliation/snapshot history, credential references, and access-path indexes are
represented. The synthetic seed contains no real account data.

Focused migration tests passed during implementation, including clean disposable database upgrade, repeated upgrade, and Alembic drift checking. Authoritative `make test-migrations` evidence remains pending at the corrected final `main` SHA.

## 6. Tests and builds

Intermediate focused and runtime evidence is recorded in the root `VALIDATION_REPORT.md`.
The complete `make validate` aggregate passed in the working tree, including unit,
property, contract, PostgreSQL/Redis integration, migrations, security, coverage,
desktop/mobile browser E2E, documentation, dependency audit, package builds, and all six
container builds. The commands deliberately remain pending for one immutable candidate
SHA rerun; the final pull request must record that exact-SHA exit status and counts.

All four application images were rebuilt and exercised under isolated Compose project
`t212pi_phase1_final_20260831`. API, worker, MCP, and web ran as UID `10001` and were
healthy. An authenticated API-backed browser probe, durable queued-run worker restart,
full-stack restart, canonical state/hash comparison, and runtime secret-canary scan
passed in the working tree. These results must be repeated at the release SHA.

## 7. Security scan architecture and status

Focused method-rejection, authorization, secret-canary, redaction, architecture, and MCP
security tests passed subsystem runs. The runtime canary was absent from API, worker,
MCP, and web logs and from `/app` and `/opt/venv` in each previously exercised image.

GitHub code-scanning upload is unavailable for this user-owned private repository under
its current entitlement, so CodeQL is not represented as a pending runnable gate. The
blocking private-repository SAST replacement is Semgrep CE `1.175.0`, pinned by image
digest, using only repository-local rules, disabled metrics, no external upload, no
network, a read-only source mount, and bounded temporary filesystems. The same command is
available through `make sast-check` and runs in the required security workflow.

Container remediation is implemented structurally: derived PostgreSQL `18.6` and Redis
`8.10.1` images upgrade the affected OpenSSL packages and run as their unprivileged
upstream users; the PostgreSQL image removes unused `gosu` and Debian snake-oil key
material; Python application images remove `pip`/`setuptools` from their runtime virtual
environments plus global runtime `pip`/`ensurepip`; and the web runtime removes npm, npx,
Corepack, and global package-manager modules. Hardened PostgreSQL/Redis startup on
disposable volumes passed as users `postgres`/`redis`, and non-root runtime/import probes
passed for all four application images. Trivy `0.74.0` is pinned in CI for repository
dependency/secret/misconfiguration/license scanning and for all six runtime images. The
complete working-tree security matrix is clean: Semgrep evaluated 7 local rules over 142
targets with 0 findings; a pre-evidence Gitleaks scan covered 54 commits and 2,156,648
bytes with exit `0`; Trivy's
vulnerability/secret/misconfiguration/license filesystem scan returned exit `0`; and all
six current images returned no findings from high/critical vulnerability and secret
scans. All workflow actions are commit-SHA pinned and all external Docker `FROM` bases
are digest pinned. These are working-tree results, not substitutes for the final
release-SHA CI rerun.

No broker credential was committed or used during implementation. `.env.example` keeps database, broker, signing, issuer, and external telemetry secrets blank; Compose substitutes its documented `portfolio` database credential only as a local, non-production fixture default. Job payloads identify owner/account/run but do not carry provider credentials.

## 8. Browser and MCP validation

The web subsystem reported passing component/state tests, a production build, and
desktop/mobile Playwright tests in the intermediate working tree. The API-backed browser
path starts the actual FastAPI service against PostgreSQL, completes local sign-in,
renders the exact canonical total `248431.27` EUR, exposes
`provider_history_coverage_gap`, shows no mobile overflow, and produces zero console
errors. Its session cookie is `HttpOnly` and `SameSite=Strict`.
Retained evidence is available as
[API-backed desktop overview](evidence/api-backed-overview-desktop.png) and
[API-backed mobile quality state](evidence/api-backed-quality-mobile.png).

The same API-backed harness persists a retained synthetic reconciliation run through the
real quantity/cash bridge algorithms. Both `quantity_mismatch` and `cash_mismatch` are
stored as immutable discrepancies and returned identically by REST and MCP; desktop and
mobile web tests render the unreconciled banner and both exact observed values. This
closes mandatory synthetic scenario 8 without pretending that Trading 212 supplies a
real opening-history basis.

The MCP subsystem reported exact nine-tool discovery, schema/annotation/auth/negative/parity
tests, health probes, widget browser validation, and Python distribution builds. The local
runtime API/MCP comparison returned identical `248431.27` EUR totals before and after the
full-stack restart. MCP Python SDK `2.1.1` does not expose tool `securitySchemes` as a
top-level descriptor field; the candidate emits the documented compatibility metadata
under `_meta.securitySchemes` and has an explicit contract test that prevents this
limitation from being silently hidden. Real MCP Inspector and ChatGPT Developer Mode
validation remain external until public HTTPS/OAuth deployment exists.

## 9. External validation not performed

- Trading 212 Demo: no owner-provided read-only Demo API key/secret; therefore the real probe did not run.
- Trading 212 Live: intentionally not authorized and not required.
- Production deployment: no remote host/domain, production identity provider, or external secret backend was selected.
- ChatGPT Developer Mode: no deployed authenticated public HTTPS MCP endpoint exists.

These external gates do not excuse a local failure and do not authorize fabricated connectivity claims.

## 10. Known limitations and release constraints

- The Demo smoke intentionally exercises only account summary and positions and cannot substitute for full fixture/contract coverage of the frozen ten-capability adapter.
- Mandatory scenario 8 passes with a retained synthetic immutable quantity/cash mismatch
  fixture. Real Trading 212 quantity and cash movement reconciliation remains explicitly
  unavailable when no valid opening-history coverage exists; the implementation does not
  fabricate an opening balance or force a real-provider bridge to reconcile.
- Local mode uses an explicit deterministic synthetic identity and local-only authentication. Production composition fails closed until real authentication, secret backend, and canonical persistence/service adapters are configured.
- Redis coordinates rate/queue state but is not authoritative financial storage.
- Provider beta-schema drift remains fail-closed; unsupported data becomes explicit partial/unavailable state instead of being coerced.
- The MCP SDK descriptor limitation described above must be rechecked when upgrading the SDK and during real ChatGPT registration.

## 11. Phase 2 prerequisites

Before Phase 2 begins:

1. complete every local Phase 1 release-SHA gate;
2. obtain owner review and disposition of the Phase 1 pull request;
3. run and retain the Demo-only external smoke result;
4. resolve production host/auth/secret-backend choices before deployment claims;
5. validate the deployed MCP endpoint with Inspector and ChatGPT Developer Mode;
6. preserve Phase 1 calculation versions, source provenance, and exact-decimal contracts as migration inputs.

This report does not authorize virtual Pies, optimization, look-through, benchmark attribution, advanced risk, scenarios, or order execution.

## 12. Owner Demo smoke procedure

Follow [Credentials and Demo Validation](../operations/CREDENTIALS_AND_DEMO_VALIDATION.md). In a private shell, disable history, load the Demo key and secret without echoing them, explicitly set the Demo-only opt-in, run `make smoke-trading212-demo`, save only the sanitized JSON result, unset the variables, and restore history. Never paste the values into chat, Git, a command argument, a URL, browser storage, or the smoke artifact.

The smoke passes only when both permitted Demo GETs return schema-valid results and the script emits `"result": "passed"`. Invalid credentials, wrong environment, schema drift, timeout, rate limit, or any incomplete response is a failure or explicit external block, never a pass.
