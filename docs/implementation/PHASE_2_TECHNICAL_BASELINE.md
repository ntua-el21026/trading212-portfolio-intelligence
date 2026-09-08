# Phase 2 Technical Baseline

**Status:** Accepted

**Date:** 2026-09-07

**Release:** 0.2.0

## Accepted starting point

Phase 1 corrected evidence is `99df47b6633791c3900a52f46f56d48be922a436`, with
migration head `20260907_0008`, nine MCP tools, ten Trading 212 GET capabilities,
371 isolated and 73 service-backed Python tests, 85% branch-aware coverage,
22 web unit tests, and 32+6 browser tests. These are the inherited regression
floor and evidence, not Phase 2 results.

## Runtime and dependencies

| Component | Pinned starting version |
|---|---|
| Python | 3.13.15 |
| uv | 0.12.7 |
| Node.js | 24.20.0 |
| pnpm | 10.34.5 through Corepack |
| PostgreSQL | 18.6, hardened digest-pinned runtime |
| Redis | 8.10.1, hardened digest-pinned runtime |

Existing manifests and locks remain authoritative for every library. No upgrade
is required by this design delta. A new rendering/provider dependency must be
necessary, pinned exactly, reviewed against primary documentation and license
terms, locked with the existing package manager, and pass all security/image
gates in the same capability increment. Do not install a system Python package,
additional Docker daemon, competing JavaScript lockfile, or global toolchain.

## Package responsibilities

| Existing package/application | Phase 2 responsibility |
|---|---|
| domain | Immutable target/reference/report/alert identities, values, validation invariants |
| analytics | Pure deterministic target/drift/optimizer/performance/X-ray calculations |
| application | Typed authorized use cases, immutable views and fixed-purpose provider/job ports |
| persistence | Normalized PostgreSQL models, scoped repositories, immutable records and durable jobs |
| trading212 | Sealed unchanged ten-capability read client; selected safe export metadata |
| worker | Replay/provider ingestion, report generation, alert evaluation and fixed job handlers |
| api | Strict additive HTTP contracts, authentication, CSRF and serialization |
| mcp | Exact registry, scopes, canonical service calls and accessible resources |
| web | Existing Next.js routes/design system, server API adapters and interactive presentation |
| observability/security | Bounded telemetry, authorization, privacy and transport policy |

Keep pure calculations free of SQL, HTTP, FastAPI and MCP imports. New provider
adapters may occupy a dedicated workspace package only when dependency isolation
requires it; update workspace, build, typing and container manifests together.
No generic HTTP request service or arbitrary job dispatcher is public.

## Data and deterministic calculation boundaries

Use `ExactNumeric` NUMERIC(38,18), `UTCDateTime`, typed currencies, the existing
fixed 80-digit Decimal context, and documented rounding at persistence/serialization.
The bounded target hierarchy uses a local 160-digit context for exact products
across at most eight 18-decimal weights; this does not change the global context.
Quantized leaf weights disclose their residual instead of silently renormalizing.
[ADR-0017](../adr/ADR-0017-DECIMAL256-EXACT-XRAY.md) adds only the closed X-ray
Decimal256 coefficient exception: `xray_v1` 1.1.0 with numeric policy
`xray_decimal256_exact_q18_v1`. Role-bounded private exact-state strings decode
directly to Decimal; public/normalized fields remain Q18 NUMERIC(38,18). Use exact
divmod HALF_EVEN, post-carry overflow rejection and explicit zero representation
bounds. Never route private coefficients through the ordinary numeric decoder or
mutate global context. Full input/result canonical bytes are each bounded at 32 MiB;
the derived content digest excludes itself and generated/current-access envelopes.
Reject binary-float financial input, NaN, infinity, naive time, excessive scale,
unknown enum values and unbounded strings/collections before application work.
UUID/source IDs and ordered canonical input hashes identify immutable inputs.
Canonical JSON uses sorted keys, exact decimal strings, UTC instants and stable
list order; generated job IDs and wall-clock timestamps are outside reproducible
semantic manifests. Persist their actual output-byte hashes separately.

## Local operation and validation

Reuse `make bootstrap`, `make validate`, `make generated-check`,
`make run-local`, `make migrate`, and the existing worker/dispatcher services.
Extend working targets to discover Phase 2 tests and fixed handlers; no no-op
or unconditional-success target is permitted. Local replay fixtures require no
provider credentials and cannot dispatch real broker requests. Explicit external
configuration states must remain visible in the API, web, MCP and reports.

Every runtime image remains non-root, package-manager-free and digest-scanned.
Application root filesystems remain read-only with dropped capabilities and
no-new-privileges. PostgreSQL retains required writable authoritative storage;
Redis remains replaceable coordination state.
