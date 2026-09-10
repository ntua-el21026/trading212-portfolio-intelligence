# Phase 2 Execution Manifest

**Status:** Accepted

**Date:** 2026-09-07

**Target:** 0.2.0 Portfolio Intelligence

**Execution branch:** main only

## Entry gate

Stage A is accepted at `99df47b6633791c3900a52f46f56d48be922a436`. No Phase 2
code preceded that acceptance. Preserve this immutable evidence and all Phase 1
regressions. The current design closure does not claim a Phase 2 capability works.

## Ordered delivery

| Package | Required coherent vertical capability | Completion evidence |
|---|---|---|
| P2-01 | [Virtual portfolios, hierarchy, targets, mappings, validation, immutable publication/lifecycle and audit](P2_01_VIRTUAL_TARGETS.md) | Scoped PostgreSQL/API/editor/read tool tests; invalid weights, immutable versions, comparison, CSRF, concurrency |
| P2-02 | [Actual/target drift and deterministic no-sale contribution plans in all required modes](P2_02_CONTRIBUTION_PLANNING.md) | Hand-calculated fixtures, properties, constraints/infeasibility, stored plan and API/web/MCP parity |
| P2-03 | [Typed market/FX/benchmark inputs, immutable snapshots, licensing and replay](P2_03_REFERENCE_SOURCES.md) | Revision/gap/cutoff/FX tests, provider isolation and explicit configuration states |
| P2-04 | Historical performance, benchmark, attribution, dividends and cash flows | Flow separation, period/currency alignment, reference returns and residual/coverage tests |
| P2-05 | [Economic identity, constituents, effective exposure and overlap](P2_05_PORTFOLIO_XRAY.md) under [ADR-0017](../adr/ADR-0017-DECIMAL256-EXACT-XRAY.md), xray_v1 1.1.0 | Independent Decimal256/Q18 money/unit and representative-root proofs; two ETFs/direct holding/share classes/ADR/unresolved/stale fixtures; licensed, bounded projection/purge and same-run canonical parity |
| P2-06 | [Private durable reports and PDF/CSV/JSON/XLSX exports](P2_06_REPORTS_AND_EXPORTS.md) | Canonical manifest, format validity, injection, authorization, expiry, licensing and restart tests |
| P2-07 | Versioned rules, scheduled evaluation, deduplication/cooldown, event feed and delivery state | All rule families, acknowledgments/resolution, quality suppression, SSRF negatives and recovery |
| P2-08 | Complete analytical web information architecture and interactions | API-backed desktop/mobile, URL/back-forward, pagination, accessibility, visual and parity evidence |
| P2-09 | Complete 25-tool MCP registry and high-value accessible resources | Exact schemas/scopes/annotations, two durable idempotent commands, cross-owner/CSP and canonical parity |
| P2-10 | Full local hardening, retention, query/load analysis, operations and release evidence | All 40 scenarios plus every local gate at one immutable SHA, all CI and fresh Compose restart |

Backend capabilities must have their functioning API, generated contracts and
appropriate web/read-tool surfaces when marked complete. P2-08/P2-09 integrate
and validate the full product experience; they do not excuse unfinished earlier
vertical capabilities. The frozen registry is planned inventory until each tool
has an implemented canonical service.

P2-05 entry requires the narrow ADR-0017 and synchronized authorities to be reviewed
and applied after P2-04 evidence closure, before dependent code. ADR-0017 fixes
shared physical row/byte budgets, bounded path proofs and the complete position-
then-cash real UUID ordering. This authority amendment does not complete evidence;
P2-05 has [scoped exact-source acceptance](P2_05_PORTFOLIO_XRAY.md) at
`7b102663ea193b4668924a7252180731954f4b00`. P2-06 is in progress from synchronized
`5ff85b4436ec9be886639e6e2cf0c722fc0c4a73`; exact-source acceptance remains pending.
P2-07 through P2-10 and Phase 3 stay not_started. P2-08 owns intelligence-data-quality/company actual-weight enrichment;
company target drift still requires a separately pinned entity-target basis.

## Work-package protocol

Before editing, inspect current main, recent history, applicable agent guidance,
current schemas, tests and dependencies. Implement the smallest coherent complete
capability; migrations, generated files and documentation move with it. Run
focused checks first, then relevant format/lint/type/unit/property/contract,
PostgreSQL/migration/security/browser/build gates. Review the full staged diff,
synchronize main immediately before committing, commit directly, push, verify
remote SHA and CI, and correct any regression in a forward commit. Do not create
branches or pull requests, rewrite published history, or tag a release here.

Status records contain P2-01 through P2-10. Percentage equals completed packages
out of ten; design closure is tracked separately and never substitutes for a
working package. `implemented_unverified` and `complete` are distinct. Retain
Phase 1 accepted evidence and Phase 3 not_started throughout.

## Acceptance and evidence contract

The [acceptance matrix](PHASE_2_ACCEPTANCE_MATRIX.md) and
[40-scenario ledger](PHASE_2_SCENARIO_EVIDENCE.md) must identify each requirement,
its executable test or operational procedure, actual result and immutable source
SHA. Pending rows cannot cite invented test files or future commands as evidence.
The final implementation report inventories migrations, models, APIs, generated
client, routes, MCP tools, methods, providers/licenses and external limitations.

Use the [test strategy](../engineering/PHASE_2_TEST_STRATEGY.md) and
[operations extension](../operations/PHASE_2_OPERATIONS.md). A locally resolvable
failure is repaired before continuation. An external provider without credentials
is represented by a typed port, replay fixture and explicit unavailable state.
Only the owner's stated genuine stopping conditions permit an incomplete delivery.
After all locally executable Phase 2 work passes, stop; do not begin Phase 3.
