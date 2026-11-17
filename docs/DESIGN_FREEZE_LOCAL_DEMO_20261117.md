# Accepted Local/Demo Architecture Baseline

**Status:** Accepted additive architecture freeze.
**Effective date:** 17 November 2026.
**Owner:** Michail Athanasios Peppas.
**Reviewed implementation:** `cd2ff67be870983b4a321d49b8d33bdc68d8ed2d`.
**Acceptance scope:** Implemented LOCAL/DEMO functionality, responsive UI, synthetic
demonstrations and documented targeted qualification.

## Authority and acceptance

The [owner acceptance](implementation/LOCAL_DEMO_ACCEPTANCE_20261117.md) records
the LOCAL/DEMO decision following the coordinator's scoped
independent review of the implementation, architecture, screenshots and retained
evidence. As reported by the owner, that review included 981 final-snapshot frontend unit tests, a separate
55-test focused frontend execution, two Python fixture-clock tests, scoped typing,
lint and documentation checks, and integrity verification of the 481-member private
evidence archive. Broader browser and database-backed executions retain their
original source qualifications; they were not independently rerun by that review.

This document records the implemented baseline under the
[design authority order](DESIGN_INDEX.md) and
[documentation governance](DOCUMENT_GOVERNANCE.md). The
[v0.1 foundation](DESIGN_FREEZE_V0_1.md),
[v0.2 delta](DESIGN_FREEZE_V0_2.md),
[v1.0 delta](DESIGN_FREEZE_V1_0.md), accepted ADRs and financial/security contracts
remain authoritative. Historical freezes and their phase-specific inventories are
preserved. This additive record introduces no service, calculation, capability,
migration, dependency or policy change.

LOCAL/DEMO acceptance is complete within its defined scope. Formal Phase 3
qualification remains separate: **Checkpoint B is incomplete; all 30 acceptance
rows and 48 scenarios remain pending, with zero formally accepted; P3-10 is
unstarted**. The accepted milestone does not establish production certification,
real-account/provider validation, CI success or redistribution rights. The
[implementation record](implementation/LOCAL_DEMO_IMPLEMENTATION_20261117.md),
[route coverage](implementation/LOCAL_DEMO_ROUTE_COVERAGE_20261117.md) and
[traceability overlay](implementation/LOCAL_DEMO_TRACEABILITY_20261117.md) retain
the evidence and its limits.

## A. System architecture

The implementation is a mixed Python/TypeScript monorepo. Application services
coordinate authorization, canonical inputs and persistence; interfaces transport or
present their results. Pure domain and analytical code does not dispatch provider
requests. Workspace manifests and lockfiles at the reviewed snapshot identify the
dependency baseline; this freeze authorizes no dependency upgrade.

| Boundary | Implemented responsibility and source |
| --- | --- |
| Web/PWA | Next.js App Router, React and TypeScript; server-side authenticated loaders, typed generated clients, narrow client interaction components and public-only offline fallback. See [web manifest](../apps/web/package.json), [root layout](../apps/web/app/layout.tsx) and [runtime gates](../apps/web/lib/runtime.ts). |
| HTTP API | FastAPI composition root for versioned, bounded portfolio, analytical, research, reporting and internal-command contracts; [API composition](../apps/api/src/trading212_api/main.py). |
| Shared Python packages | `domain` defines values and invariants; `analytics` implements financial methods; `application` owns use cases; `persistence` owns relational stores; `trading212` and `reference-data` isolate providers; `security` and `observability` supply cross-cutting controls. See [workspace definition](../pyproject.toml). |
| PostgreSQL | Authoritative financial observations, immutable analytical inputs/results, owner/account relationships, job/outbox state, retention membership, audit and retained report/artifact records. Exact numeric and UTC boundaries are implemented in [persistence types](../packages/persistence/src/trading212_persistence/types.py); [ADR-0003](adr/ADR-0003-POSTGRESQL-SYSTEM-OF-RECORD.md) remains binding. |
| Redis | Non-authoritative delivery and coordination infrastructure. Compose configures Celery broker DB 0, temporary Celery result backend DB 1 and Trading 212 rate coordination DB 2. The [rate coordinator](../apps/worker/src/trading212_worker/rate_coordinator.py) stores bounded cooldowns under hashed account/capability identities. Redis does not own financial truth or durable job identity. |
| Background execution | The existing [Celery worker](../apps/worker/src/trading212_worker/tasks.py) consumes fixed typed task families. The separate [PostgreSQL outbox dispatcher](../apps/worker/src/trading212_worker/outbox_dispatcher.py) claims, publishes and retries durable work, and runs bounded maintenance cycles. There is no additional queue service or Celery Beat process in the accepted Compose topology. |
| MCP | Authenticated Streamable HTTP composition over the same application services: **38 tools, comprising 33 reads and five bounded internal commands, and 11 HTML resources**. See [runtime registration](../apps/mcp/src/trading212_mcp/server.py), [registry contract](integrations/PHASE_3_MCP_TOOL_REGISTRY.md) and the [38-tool/11-resource regression contract](../tests/contract/test_research_mcp_contract.py). Hosted ChatGPT registration remains unverified. |
| Providers | The sealed Trading 212 client admits only the ten capabilities in section C. Market/FX/ETF/research adapters use separate typed, licensed source contracts; unavailable configuration remains explicit. Browsers and MCP resources have no direct broker access. |

The five MCP commands create internal contribution plans, portfolio reports, risk
runs, scenario runs and projection runs. They never execute trades or select
arbitrary provider operations. The 11 resource views are snapshot, contribution
plan, performance comparison, X-ray, report status, risk, scenario, projection,
research, allocation and drift; their resource CSP does not grant external network
access.

Durable admission commits job identity and outbox intent in PostgreSQL. Dispatch
and consumption use bounded attempts, leases, current fences and idempotent
publication. A stale worker cannot publish a completed result; interrupted work
retains its canonical identity. Redis loss can delay the configured pipeline,
while PostgreSQL retains durable work and results. Non-authoritative Redis is
still a dependency of the configured Compose worker/dispatcher; it is not an
optional replacement for PostgreSQL-backed recovery. These choices preserve
[ADR-0020](adr/ADR-0020-PREMIUM-DURABLE-WORK.md).

[Compose](../compose.yaml) defines seven long-running services: PostgreSQL, Redis,
API, worker, dispatcher, MCP and web. `migrate` and `seed` are one-shot services.
The local configuration publishes loopback endpoints, uses a synthetic worker
provider and separates persistent PostgreSQL data from temporary worker scratch
storage. Container definitions and deployment examples do not constitute an
accepted production deployment.

## B. Financial correctness and data meaning

The [financial calculation policy](analytics/FINANCIAL_CALCULATION_POLICY.md) and
[quality/reconciliation policy](analytics/DATA_QUALITY_AND_RECONCILIATION.md)
remain binding:

- Identical canonical inputs, valuation/source cutoffs, numerical profile,
  methodology version and declared options produce deterministic authoritative
  outputs. Browser chart coordinates and formatted labels do not become a second
  financial engine.
- Monetary amounts, quantities, prices, FX and authoritative ratios use validated
  `Decimal` values and exact database `NUMERIC`; public financial fields remain
  bounded decimal strings. [Domain values](../packages/domain/src/trading212_domain/values.py)
  reject binary-float inputs, nonfinite values and invalid scale/range. Declared
  rounding and residuals remain separate from display precision.
- The existing ordinary, target-hierarchy, exact X-ray and premium numerical
  profiles retain their distinct precision, rounding and tolerance contracts.
  [ADR-0017](adr/ADR-0017-DECIMAL256-EXACT-XRAY.md) governs exact X-ray coefficients;
  [ADR-0019](adr/ADR-0019-PREMIUM-NUMERICAL-METHODS.md) governs finite-precision
  risk/statistics/projections. Deterministic approximate statistics remain model
  estimates, not mathematically exact observations or forecasts.
- Every monetary value has an explicit currency. Conversion requires an explicit
  sourced FX direction, observation and policy. Missing FX never defaults to one;
  listing currency does not establish underlying economic exposure.
- Internal instants are timezone-aware UTC. Source time, retrieval time,
  valuation time and calculation time remain distinguishable. Pinned cutoffs
  exclude later knowledge; immutable results retain their original source and
  method identity.
- Deposits and withdrawals are external flows; security purchases and sales are
  internal exchanges. Reconciliation preserves quantity, cash, portfolio-value
  and investment-result bridges where evidence supports them, with explicit
  tolerances and residuals. Provider-reported and internally derived values
  remain distinguishable.
- Missing inputs, unavailable values, stale, partial, estimated, unreconciled and
  failed states remain distinct from a valid zero. Coverage, provenance,
  assumptions and warnings accompany results. Material gaps degrade or withhold
  affected metrics without silently inventing values or redistributing unknown
  exposure into known holdings.

Versioned risk, stress, projection, research and aggregation implementations remain
available in the accepted application. Their presence and LOCAL/DEMO acceptance
do not replace the pending complete Phase 3 numerical/scenario qualification.

## C. Security, privacy and broker isolation

The [security architecture](security/SECURITY_ARCHITECTURE.md),
[Phase 3 privacy contract](security/PHASE_3_SECURITY_PRIVACY.md) and
[Trading 212 contract](integrations/TRADING212_API_CONTRACT.md) continue to govern
the implementation. The [machine-readable allowlist](../config/contracts/trading212-read-allowlist.yaml)
and [sealed registry](../packages/trading212/src/trading212_provider/allowlist.py)
contain exactly these **GET** capabilities:

| Capability | Fixed path template |
| --- | --- |
| `account_summary` | `/equity/account/summary` |
| `metadata_instruments` | `/equity/metadata/instruments` |
| `metadata_exchanges` | `/equity/metadata/exchanges` |
| `portfolio_positions` | `/equity/positions` |
| `pending_orders` | `/equity/orders` |
| `order_detail` | `/equity/orders/{order_id}` |
| `historical_orders` | `/equity/history/orders` |
| `historical_transactions` | `/equity/history/transactions` |
| `historical_dividends` | `/equity/history/dividends` |
| `historical_exports` | `/equity/history/exports` |

Unknown methods, capabilities, path/query parameters and arbitrary URLs fail
before broker transport. Redirects and automatic path discovery remain disabled.
There is no order execution/cancellation/amendment, broker Pie mutation, payment,
transfer, CFD or generic HTTP/broker capability. Historical export listing does
not grant permission to create a broker export or follow provider download URLs.
Application reports and virtual targets are internal resources.

Authentication is resolved server-side; current principal scopes and owner/account
relationships authorize operations. Resource IDs and pinned historical grants do
not confer access. Local synthetic authentication is explicitly gated to local/test
operation; deployed authentication remains fail-closed without its required
configuration. Cookie-authenticated internal commands preserve same-origin/CSRF,
idempotency and audit controls. Account switching and late-response guards prevent
an earlier account's content from replacing the selected account.

Broker credentials resolve through server-side secret interfaces. Public models,
client bundles, MCP results, ordinary logs and reports exclude credential values
and signed download URLs. Research text is inert untrusted content: it cannot
change scopes, choose arbitrary URLs, invoke commands or supply authoritative
financial facts. Optional model synthesis and paid-provider activation remain
outside the accepted demonstration.

Report generation and downloads preserve owner/account/profile identity, exact
source revisions/digests and distinct REPORT/EXPORT permissions. Current grants,
source licenses, expiry and transitive dependencies are checked before private
payload decoding; see [scalar report-source gates](../packages/persistence/src/trading212_persistence/report_sources.py).
The existing research contract selects one exact item, 0–64 immutable note
revisions and an optional exact review acknowledgment, without a latest-version
fallback. PDF, CSV, XLSX and JSON artifacts retain bounded processing, canonical
manifests, byte lengths and SHA-256 identities. The
[server-only download bridge](../apps/web/lib/report-download.ts) uses typed
short-lived grants and private, no-store responses.

Retention is constrained by original-source rights and the applicable run/report
policy, including derived copies. Revocation or expiry denies access before
bounded physical cleanup completes. These are implemented controls with retained
positive/negative tests; the freeze does not imply that every historical retention,
recovery or adversarial predicate has passed at one final SHA.

## D. UI and PWA architecture

One semantic `--pi-*` palette in [global CSS](../apps/web/app/styles.css) supplies
light/dark colors, status families, focus, controls, charts, spacing, typography,
radii and elevation. Compatibility aliases serve existing components. The
[shared UI package](../packages/ui/src/index.tsx) retains reusable surfaces,
buttons, status indicators, notices, skeletons, empty states and visually hidden
text; feature CSS Modules consume the same tokens. Existing Recharts and Lucide
dependencies are reused. The redesign adds no remote font or new dependency.

The bounded `pi_theme_v1` cookie stores only `light`, `dark` or `system`. The
[server layout](../apps/web/app/layout.tsx) emits the validated root attribute,
matching initial client preference and browser theme metadata. CSS resolves system
preference before hydration and tracks OS appearance changes. The narrow
[client provider](../apps/web/components/theme.tsx) updates the root, cookie,
controls and browser chrome. Appearance is independent of authentication and
account identity; it survives navigation, reload and sign-out where cookie
persistence is available. Restricted persistence still permits changing the
current document. Cookie reads make the root request-dependent; no preference
endpoint/table or unsafe inline bootstrap is introduced.

The responsive shell retains all navigation destinations, account selection,
command palette, skip link, keyboard controls, focus reveal, named scrollable
tables, reduced-motion behavior and safe-area allowances. The sidebar navigation
scrolls above its footer; mobile controls can wrap in normal document flow.
Charts plot server values with theme-aware axes/series/tooltips, preserve missing
gaps and original-value formatting, and retain canonical table alternatives.
Illustrative mockup figures, unsupported history curves and new financial features
are not part of the implementation.

The accepted inventory contains **32 page-route patterns**, separately from seven
existing HTTP bridges:

| Area | Existing page routes |
| --- | --- |
| Portfolio observations | `/`, `/holdings`, `/holdings/[positionId]`, `/allocation`, `/activity`, `/dividends` |
| Operational views | `/snapshots`, `/synchronization`, `/quality` |
| Internal targets/planning | `/pies`, `/pies/[portfolioId]`, `/drift`, `/planner`, `/planner/[planId]` |
| Sources | `/sources`, `/sources/benchmarks/[definitionId]`, `/sources/snapshots/[kind]/[snapshotId]` |
| Historical/current analytics | `/performance`, `/income`, `/xray`, `/xray/sources/[snapshotId]`, `/risk`, `/aggregation` |
| Modeled analysis | `/scenarios`, `/projections` |
| Research/reporting/alerts | `/research`, `/reports`, `/reports/premium`, `/alerts` |
| Preferences/access | `/settings`, `/settings/layouts`, `/sign-in` |

The [route inventory](implementation/LOCAL_DEMO_ROUTE_COVERAGE_20261117.md)
identifies each component, bridge, test contract and actual browser observation.
Representative browser execution covers 27 patterns; five deep routes retain
source/shared-regression coverage without a fresh dedicated browser journey.
Palette contrast checks, responsive captures, CSS-magnification stress and native
viewport reflow are scoped evidence, not native-browser-zoom measurement or a
comprehensive accessibility certificate.

The [service worker](../apps/web/public/sw.js) caches only an explicit public
versioned shell/asset allowlist. Authenticated HTML, RSC, API responses, reports and
tokens remain outside that cache; offline failure cannot masquerade as a
successful financial response. The immutable public offline-v1 shell retains an
intentional fixed-dark palette and strict no-JavaScript CSP. It does not follow
the workspace appearance cookie. A future change needs versioned asset/cache
compatibility review rather than alteration of retained v1 bytes.

## E. Operational and qualification boundaries

LOCAL supports the authenticated synthetic API/worker/database composition; the
explicit synthetic DEMO provides browser-facing portfolio examples. The
[local runtime gates](../apps/web/lib/runtime.ts) reject synthetic authentication
outside local/test environments. Synthetic Demo entry does not contact Trading
212. Local operation follows the existing [runbook](operations/LOCAL_AND_DEPLOYMENT.md);
this document introduces no new startup, migration, reset or cleanup operation.

External Demo/provider verification requires separate credentials, entitlements
and authorization. Trading 212 Live, public deployment, production identity,
monitoring ownership, production backup/restore and signing attestations, paid
providers, hosted OAuth/MCP/ChatGPT registration, and binary/container distribution
remain separately gated. All three GitHub workflows remain owner-disabled and
unverified. Public source visibility does not establish rights to redistribute
dependencies, binaries, container images or licensed source data.

The accepted scope retains documented limitations: original admission-p95 failures,
whole-Web-tree byte-repeatability failure, nonzero historical secret-scanner exits
with separately reviewed nonsecret matches, a documented framework/dependency
advisory, five deep routes without fresh browser execution, the fixed-dark offline
fallback and unrerun broader Phase 3 suites. Two previously unclassified Redis
keys, original databases/volumes, private archives and development environments
remain preserved. Their retention does not establish disposal rights or authorize
cleanup.

Detailed results remain in the [implementation record](implementation/LOCAL_DEMO_IMPLEMENTATION_20261117.md)
and [validation report](../VALIDATION_REPORT.md). The
[semantic-repeatability and scanner-disposition proposals](verification/LOCAL_DEMO_CONTRACT_PROPOSALS_20261117.md)
remain proposals; this acceptance does not approve them, weaken thresholds or
convert a nonzero execution into a pass. These limitations inform later broader
qualification and deployment decisions while retaining the explicit bounded
LOCAL/DEMO acceptance.

## F. Future change control

This freeze establishes an accepted baseline for assessing later changes. Any
material architectural change requires an **explicit new owner decision**, with
an accepted superseding ADR where required by
[documentation governance](DOCUMENT_GOVERNANCE.md), followed by synchronized
contracts, tests, status and evidence. Historical freezes and execution results
remain attributable to their original scope and source.

Material changes include financial/numerical semantics or tolerances; canonical
schema or migration compatibility; source provenance, quality or retention;
authorization, tenant isolation, credential or artifact boundaries; provider/MCP
capabilities; durable-work/storage topology or resource ceilings; theme/cache
privacy behavior; dependency/runtime changes with architectural consequences; and
CI, deployment, licensing or distribution policy. Routine compatible maintenance
must preserve these invariants and receive the task authorization appropriate to
its scope.

No subsequent implementation phase, broker expansion, production operation,
release/distribution, CI activation or P3-10 execution is authorized by this
document. Independent acceptance of broader Phase 3 requirements requires its
own explicit decision and source-qualified evidence.
