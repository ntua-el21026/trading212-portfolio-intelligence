# Portfolio Intelligence Design Delta v0.2

**Status:** Accepted

**Date:** 2026-09-07

**Scope:** Phase 2, release 0.2.0; implementation is not yet accepted

## Authority and entry evidence

This additive delta is authorized by the owner's continuous Stage A/Stage B
assignment. Phase 1 passed every local and CI gate at
`99df47b6633791c3900a52f46f56d48be922a436`; its evidence is preserved in
[the independent audit record](implementation/PHASE_1_AUDIT_CORRECTIONS.md).
This delta extends v0.1 for Phase 2 only. The original safety, financial,
identity, privacy, and direct-main rules continue to apply.

Accepted ADRs 0009 through 0016 resolve the consequential Phase 2 decisions.
If an implementation requires a different decision, add a superseding ADR and
update affected contracts before depending on it. No roadmap phrase overrides
an explicit financial or security invariant.

## Release boundary

Implement P2-01 through P2-10 in order: virtual targets, contribution planning,
market/FX/benchmark inputs, historical performance and income, ETF look-through,
reports/exports, alerts, analytical web, MCP integration, and complete acceptance.
All are internal intelligence capabilities. There is no order staging, broker
write, trade approval, price prediction, research agent, Monte Carlo projection,
goal engine, or other Phase 3 capability.

Internal writes have their own scopes, owner/account authorization, CSRF where
cookie-authenticated, optimistic concurrency, idempotency, and audit. They never
translate plans into broker commands. Trading 212 remains the exact ten GET
capabilities; its sealed transport continues to reject unknown input before I/O.

## Frozen engineering choices

- Keep the existing uv/pnpm monorepo, Python/TypeScript framework versions,
  PostgreSQL authority, Redis coordination, Celery worker, and dispatcher.
- Reuse exact numeric and UTC value boundaries. Perform calculations with the
  existing fixed 80-digit Decimal context and explicit persistence rounding.
  Bounded hierarchy products use the local 160-digit context in ADR-0010 and
  retain a disclosed rounding residual. The narrow
  [ADR-0017](adr/ADR-0017-DECIMAL256-EXACT-XRAY.md) exception uses a fresh local
  Decimal256 context and role-bounded private exact coefficients for `xray_v1`
  1.1.0 / `xray_decimal256_exact_q18_v1`, with exact Q18 HALF_EVEN publication.
  Ordinary precision 80, target precision 160 and public/normalized NUMERIC(38,18) remain unchanged.
- Publish immutable analytical inputs and version every methodology. Keep source
  time, retrieval time, calculation time, and valuation cutoff distinguishable.
- Normalize owner-scoped entities and foreign keys. Persist completed jobs and
  their outbox intent transactionally; Redis alone never proves completion.
- Use typed provider-specific ports, bounded deterministic replay providers,
  explicit provider/license availability, and isolated outbound adapters.
- Preserve unclassified holdings, unresolved mappings, missing constituents,
  partial coverage and stale input. No missing financial fact becomes zero.
- Produce reports from canonical application results. Private bounded artifacts
  initially reside in PostgreSQL; an external object store is optional.
- Extend the existing design system and canonical generated client. The browser
  formats or plots server values; it does not calculate authoritative results.
- Freeze 25 MCP tools: nine compatible Phase 1 tools, fourteen new reads, and two
  idempotent non-destructive internal commands. Activate each only when its
  canonical vertical capability works; accept the full registry at P2-09.

## Implementation and acceptance

The [technical baseline](implementation/PHASE_2_TECHNICAL_BASELINE.md),
[execution manifest](implementation/PHASE_2_EXECUTION_MANIFEST.md),
[acceptance matrix](implementation/PHASE_2_ACCEPTANCE_MATRIX.md), and
[scenario ledger](implementation/PHASE_2_SCENARIO_EVIDENCE.md) are active phase
authorities. A design decision is accepted here; implementation is complete only
when its executable evidence passes. All 40 mandatory scenarios and every
locally executable row must pass at one immutable release SHA before 0.2.0 is
marked locally complete. Each coherent package is committed directly to main,
pushed, and checked in CI; Phase 1 regressions remain mandatory.

The four Phase 1 external conditions remain explicit. Missing paid data,
notification, object-storage, production identity or deployment credentials do
not block synthetic local completion and must not be portrayed as real-provider
validation. Phase 3 remains not_started.
