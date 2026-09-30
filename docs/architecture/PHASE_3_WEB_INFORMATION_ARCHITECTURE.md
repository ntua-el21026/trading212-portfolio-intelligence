# Phase 3 Web Information Architecture

**Status:** Accepted implementation design; browser validation pending

Extend authenticated account shell/tokens and preserve old routes and stable account/
snapshot/window/currency URL state. New navigation: Risk, Scenarios, Projections & goals,
Research and Aggregate; provider readiness/saved layouts in settings. Read installed
Next documentation before dependent code; retain framework/runtime/dependency pins.

Risk shows definition/version, history/calendar/basis, durable run status, observed
estimates, modeled contributions, matrices and coverage. Scenarios include editor,
exclusions, immutable history, replay and two-result comparison. Projections expose
assumptions/goals/schedule/seed, nominal/real paths, terminal distribution, shortfalls,
sensitivity and model limits. Research shows exposure-ranked entities/events, citations,
source facts versus owner theses/risks/catalysts/break conditions and revision review.
Aggregate requires explicit authorized members and account/FX/transfer coverage.

Mutations disclose effects, enforce write scopes and preserve idempotency across retry.
Cancel/discard late fetches on account/filter change and clear prior private results.
Reset cursors on filter changes. Loading/missing/zero/partial/stale/estimated/unavailable/
failed are distinct. Use generated clients and canonical numbers, no browser finance.
Charts have visible gaps, text/table alternatives and source/method captions.

Palette: button and Ctrl/Cmd+K, Escape, keyboard selection and focus restoration.
Search only closed routes/owned saved views, not arbitrary URLs/provider text. Save
<=32 owner layouts with <=24 known widgets and bounded versioned filters. Reauthorize
referenced accounts; never store tokens/provider payloads/duplicated financial results.

## Install/offline

Manifest: stable id/start_url/scope, standalone display, theme/background and local
192/512 icons with maskable variant. Feature-detect install prompt; fallback browser
instructions. Notifications require permission and configured delivery, otherwise
explicitly unavailable. No background private operation synchronization.

Worker caches only allowlisted versioned public files and dedicated public offline
document. Navigation network-first falls back solely to public unavailability, never
cached authenticated HTML. No API/auth/report/private fetch caching or tokens/headers
in storage. Offline shell offers retry. Logout clears private memory/widget state and
obsolete application shell caches. Test real CacheStorage across offline/owner changes.

## Local measured targets

No document horizontal overflow at 360x800,768x1024,1440x900. Keyboard workflows,
WCAG AA contrast, zero automated serious/critical violations plus manual focus/chart
inspection. Reduced motion disables animation. Fixed synthetic100-holding/1000-event
fixture, production Chromium build, one worker and recorded hardware: LCPp75<=2.5s,
interaction latencyp75<=200ms, CLS<=.1 over >=5 runs. Report lab, not field CWV.
Premium route first-load compressed JS<=350KiB excluding separately measured shared
runtime; disclose shared/incremental bytes and investigate >10% existing-route
regression. Do not alter thresholds/fixtures to disguise a violation.

## Implemented risk workspace

/risk uses the existing account shell and fixed generated risk/history/source/X-ray
clients. Runs, definitions, new analysis and result are typed URL views; each
collection has an independent bounded cursor. Definitions use immutable versions,
explicit calendar/frequency/rates/tail assumptions and revision checks. New analyses
show retained snapshot/history/X-ray identities before an internal command. The UI
never supplies return arrays or an owner identity. Source selections allow at most32
instruments with one licensed total-return series each, preserving choices across
source pages. Empty selection requests observed statistics only.

Results use canonical persisted metrics and labeled unavailable reasons. Rolling
charts reuse the historical renderer with explicit volatility units, disconnected
gaps, UTC day labels and exact table values. Source details retain full timestamps.
Status controls stop automatic polling after48 refreshes and suppress late command
results on navigation. All internal writes recheck session origin/CSRF and service
scopes/grants. No browser private-data cache or new Docker service is introduced.
Component evidence is described in PHASE_3_IMPLEMENTATION_REPORT; final PWA and
premium widget validation remain pending.

## Explicit multi-account workspace

`/aggregation` lists owner-authorized saved selections and calculations, creates
1–8-member selections from explicit saved snapshot choices, and presents holdings,
original components, whole-account totals and optional transfer evidence. Each
result preserves native currency, per-account valuation/source clocks, canonical
instrument identity, source references, exact decimal values and missing-FX
coverage. A matched transfer does not certify complete activity or performance.

The run form resolves saved FX references through explicit account/currency,
direct or inverse pair, retained provider snapshot and observation choices. Each
request reads at most one25-row page; there is no automatic source selection,
provider call or arbitrary observation-ID input. Server actions reload selection
membership and use the earlier of its cutoff and the member snapshot valuation,
retaining timestamp precision. Current all-member authority is checked again
before returning choices. Navigation, unmount and revision changes discard late
responses; account switches clear selections, runs and cursors. Optional activity
windows require explicit start/end instants within every member's saved cutoff.

The workspace has command-palette/navigation access, strict URL state, semantic
retry identity, exact saved revision preconditions, keyboard controls and table
alternatives. Browser scenarios use two distinct native adapters through the
actual canonical materializer and saved FX ingestion; no aggregate results are
seeded. This records implementation scope, not unexecuted performance acceptance.
