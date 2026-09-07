# Phase 2 Web Information Architecture

**Status:** Accepted

**Date:** 2026-09-07

## Product structure

Extend the existing Next.js App Router and portfolio shell. Preserve all Phase 1
routes, secure sign-in/out, synchronization and reconciliation flows. Read the
installed Next.js guides required by `apps/web/AGENTS.md` before implementation.
The public API names virtual portfolios; the user-facing product calls them Pies.

| Route | Product workflow |
|---|---|
| `/` | Portfolio overview with canonical totals, flows, quality and intelligence entry points |
| `/pies` | Search/filter/page owned virtual Pies and templates; create or archive |
| `/pies/[portfolioId]` | Hierarchy/holding/cash target editor, explicit normalization and unresolved mappings; validate, publish and compare immutable versions |
| `/drift` | Snapshot/target selection, actual versus target by group/holding/cash/unclassified, signed/absolute/relative drift and monetary gaps |
| `/planner` | Contribution currency/amount, mode, eligible scope, constraints and reserve; create immutable manual plan, inspect infeasibility/residual and prior revisions |
| `/performance` | Period/benchmark selection, value and return series, rolling/calendar views, drawdown, flows, attribution and source/method drill-down |
| `/income` | Dividend/cash-flow timelines, instrument/group/currency summaries, yield/growth/concentration with coverage |
| `/xray` | Effective company/classification exposure, direct versus indirect, ETF overlap and constituent/source drill-down |
| `/reports` | Type/period/source selections, durable report/export requests, job state, private authorized downloads, expiry and methodology |
| `/alerts` | Versioned rule editor, activate/pause/archive, event feed, severity/status filters, acknowledgment/resolution and delivery state |
| `/sources` | Market/FX/benchmark/ETF provider status, source dates, gaps, licensing and configuration availability |
| Existing `/quality`, `/settings` | Reconciliation/data quality and explicit provider/security configuration state |

Each page uses canonical application services through generated typed API clients.
There is no generic API passthrough or client-side authoritative financial math.
New commands use server-side auth/CSRF forwarding and stable typed errors.

## Interaction and state contracts

Selection, period, benchmark, target, mode, sorting, filters and cursor are encoded
in bounded URL state so reload and browser back/forward restore the view. Changing
filters resets the cursor. Collections expose exact total/continuation semantics
and never silently cap visible records. Use saved views only as owner-scoped UI
preferences with validated keys; they contain no credential or raw provider data.

Forms preserve user-entered data on validation failures, expose field/error summaries,
show optimistic revision conflicts, and make publication/version transitions clear.
Destructive archive is an internal reversible lifecycle operation. A published target
is read-only; edits begin a new version. Contribution outputs prominently state:
“Manual plan. No trades are placed.” No broker-order controls or trade staging exist.

Loading skeletons contain no invented values. Empty, stale, partial, unavailable,
unreconciled, estimated and failed results have distinct labels/actions and retain
coverage/source/method detail. Provider configuration absence cannot look like a
successful refresh, zero return, or zero unresolved exposure.

## Visual and accessibility requirements

Use the existing financial typography, spacing, tokens and responsive shell. Dense
data remains legible on desktop/tablet/mobile, with keyboard-accessible controls,
visible focus, meaningful labels/headings, screen-reader summaries and reduced
motion. Target WCAG2.2AA and no horizontal page overflow at supported mobile widths.
Responsive tables may provide an explicitly labeled internal scroll region.

Charts show consistent date scales, explicit currency/return basis/benchmark,
source gaps and quality. Do not connect missing observations as known values or
truncate axes misleadingly. Every chart has an equivalent accessible server-value
table and source/method details. Plot conversion to screen coordinates is presentation
only; labels/totals/results retain canonical decimal strings.

## Verification

Test the real API-backed create/publish/plan/report/rule workflows, owner denials,
loading/failure states, browser history, stable pagination, desktop/mobile keyboard
navigation, accessibility and screenshots. Do not accept a mock-only demo as evidence
of durable commands. Preserve Phase 1 route tests and canonical `248431.27 EUR`
synthetic evidence while extending the seeded product without duplicate economics.
