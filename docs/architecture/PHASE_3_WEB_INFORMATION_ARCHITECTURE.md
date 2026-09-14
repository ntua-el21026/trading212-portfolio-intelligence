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
