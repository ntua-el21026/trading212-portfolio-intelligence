# Codex Prompt — Gated, Whole-Application UI/UX Modernization

**STATUS: PREPARED DRAFT — DO NOT SEND OR EXECUTE UNTIL THE OWNER/REVIEWER HAS CLEARED THE PREREQUISITES.**

The following prompt is designed to be copied into **one** Codex conversation after the three design documents have been reviewed and committed. The prompt's authorization is **limited to the explicitly approved UI package** and does not grant P3-10, CI, Live, provider, deployment, or distribution authority.

---

## BEGIN COPY-READY CODEX PROMPT

You are implementing a separately approved, strictly frontend-focused UI/UX redesign in:

`ntua-el21026/trading212-portfolio-intelligence`

Environment: Windows + WSL2/Ubuntu, default Linux project directory `/home/peppasmich/projects`. Repository `main` is the **only** implementation branch. The owner expects a complete, professional, maintainable visual modernization informed by six provided PNG mockups, with both light and dark themes, without any loss of functionality.

### 0. Absolute precedence and stopping gates

Before doing anything:

1. Identify the canonical live GitHub `main` HEAD and the local `main`/`origin/main` HEAD, current branch, worktree cleanliness, changes in flight and latest committed documents. Do **not** assume any SHA in the earlier handoff is current.
2. Read `AGENTS.md`, `apps/web/AGENTS.md`, `docs/DESIGN_INDEX.md`, accepted design freezes/ADRs, active Phase 3 manifest, status/progress/acceptance/scenario evidence, security and financial authorities.
3. Read these committed, owner-reviewed draft files under `docs/design/`:
   - `UI_UX_DESIGN_SPECIFICATION.md`
   - `UI_IMPLEMENTATION_ROADMAP.md`
   - `UI_REDESIGN_CODEX_PROMPT.md`
4. Confirm **in writing** that the preceding Checkpoint B has been **independently accepted**, not merely reported complete by Codex, and that the owner has separately authorized this UI work package and resolved any design-freeze conflict.
5. If any precondition is missing, disputed or contradicted by current evidence, **STOP WITHOUT EDITING**. Report exact source SHA, missing acceptance/authority, and the smallest safe owner decision needed. Do not equate `blocked_external` with unresolved local failures. This prompt is NOT P3-10 authorization.
6. Verify there is no concurrent writer on `main` and that the local checkout is clean and synchronized. Never create a branch or PR, force-push, reset, rebase, amend published commits, or rewrite history. Use only coherent, validated, fast-forward commits directly to `main`.

This is a cosmetic frontend redesign, **not a functional rewrite**. Do not modify backend behavior, schema, migrations, financial algorithms, broker integration, authentication scopes, API/MCP contracts, security rules, dependencies or limits simply to support a visual concept. Any genuinely unavoidable expansion outside the authorized package is a stop condition requiring separate owner approval.

### 1. Find and verify the six mockups on the user's computer

Locate a ZIP named `Portfolio_Intelligence_Minimal_v2_All_6_Screens.zip` or a clearly duplicate-suffixed copy such as `Portfolio_Intelligence_Minimal_v2_All_6_Screens(1).zip` inside the **actual user's Downloads folder**. The machine may be running Windows or WSL. Discover the current Windows user's Downloads location safely through the environment; do not invent a Windows username or assume the Linux process's `~` is the Windows profile. Do not scan arbitrary private directories or reveal unrelated filenames.

Required six members:

1. `Portfolio_Intelligence_Minimal_v2_01_Overview.png`
2. `Portfolio_Intelligence_Minimal_v2_02_Holdings.png`
3. `Portfolio_Intelligence_Minimal_v2_03_Xray.png`
4. `Portfolio_Intelligence_Minimal_v2_04_Performance.png`
5. `Portfolio_Intelligence_Minimal_v2_05_Scenarios.png`
6. `Portfolio_Intelligence_Minimal_v2_06_Alerts.png`

Validate ZIP integrity and member names; reject unsafe paths, symlinks/path traversal, corrupt members, duplicates or suspicious archive structures. Extract only into a uniquely owned temporary directory outside the source repository. Inspect all six images individually; note proportions, spacing, colors, typography, charts, tables, forms and state labels. If multiple ZIP candidates exist, verify their contents rather than silently choosing the first. If the ZIP is unavailable, **STOP and request the file**; do not fabricate screenshots, palette or fidelity claims.

Do not commit the ZIP or full-resolution PNG mockups. They are **visual references**; their portfolio figures, dates, statuses and imagined controls are synthetic and not product specifications.

### 2. Independently inventory current implementation

Inspect live source, not memory:

- `apps/web` framework/version, app router, layouts, error/loading boundaries, components, CSS modules, global CSS, theme/CSP/SSR behavior, assets, PWA, sign-in, account selector and command palette.
- `packages/ui` existing primitives and styles. Refine/reuse these instead of creating parallel duplicate UI systems.
- Recharts, Lucide React and other chart/icon dependencies already pinned by the repo.
- All current navigation links, detail routes, grouped routes, settings, exports/downloads, forms, pagination, query/selection state and account authorization.
- Existing web/browser tests, API negative cases, performance gates, accessibility aids, deployment/asset restrictions and project status.

The six mockups cover Overview, Holdings, X-ray, Performance, Scenarios and Alerts, **not the complete application**. Earlier observed routes included allocation, activity, dividends, snapshots, synchronization, quality, Pies, drift, planner, sources, risk, projections, research, aggregation, income, reports, premium reports, Settings, saved layouts, sign-in and multiple details. Regenerate the route map from the current source; do not drop anything because it is absent from an image.

Before code edits, record a concise source-verified plan with: final live SHA, route/component inventory, existing primitive reuse, theme strategy (including CSP-safe no-flash behavior), design-token strategy, baseline screenshot approach, tests and any out-of-scope blockers. If plan requires expanding functionality or conflicting with accepted phase authority, STOP for owner direction.

### 3. Establish one production-quality design system

Implement the approved `UI_UX_DESIGN_SPECIFICATION.md` using existing CSS/CSS-module architecture and shared `@trading212/ui` package. Evolve legacy semantic variables systematically; avoid inconsistent local hardcoded palettes.

Visual direction:

- Premium, minimal financial SaaS: near-white or warm-neutral surfaces; dark charcoal theme; emerald accent; well-spaced typography; subtle borders/shadows; clean data density.
- Clear visual hierarchy for portfolio values, coverage and source quality. A selected nav item should be obvious without relying on color alone.
- Consistent page headers, metric cards, panels, tables, filters, buttons, controls, dialogs, tooltips, loading/empty/error states, status badges and charts.
- Professional charts using existing chart infrastructure; correct units, currencies, methodology, provenance, time axis, accessible summaries and responsive legends.
- Scalable SVG/Lucide/CSS assets where appropriate; no PNG screenshot backgrounds, heavyweight dashboard UI libraries or remote fonts.
- Modern responsive layout for desktop, tablet, mobile, narrow/zoomed screens and high-DPI monitors; preserve all route discoverability and focus behavior.

The design spec supplies **proposed**, not absolute screenshot-sampled, color tokens. Verify and refine them where accessibility or actual app components require. Any deliberate deviation must be documented and consistent across the application.

### 4. Implement complete light/dark/system mode

Implement three user choices: `light`, `dark` and `system`. Persist preference locally without creating unnecessary server resources. Apply it at the root and resolve it before meaningful first paint; inspect CSP/security and Next.js framework requirements so no-flash initialization is safe. Follow system preference changes when in `system` mode.

Theme every relevant surface, component, chart, tooltip, dialog, menu, form control, focus ring, table row and informational message. Preserve existing accessibility and scroll-focus protections. No default black-on-black or hardcoded white popup remains in dark mode. Ensure reduced-motion preferences and appropriate native color-scheme integration.

Do not invent backend preference tables, authorization scopes or network calls for theme state. Test persistence through navigation, refresh, account switching and sign-out.

### 5. Implement the six reference screens and all other existing areas

Use reference-specific layout principles **only where real features/data support them**:

- Overview: strong valuation hierarchy, real history/coverage chart when available, allocation and holding context, explicit trust/provenance.
- Holdings: modern searchable/filtered table and details; real sparklines only when source-qualified; preserve full position fields, quantities, FX, P/L and unavailable states.
- X-ray: sophisticated treemap/breakdowns and **visible unresolved/unknown** exposures; preserve source/fund detail and actual quality contracts.
- Performance: comparative charts, drawdown/return displays and period controls where backed by actual implementation; preserve correct benchmark methodology and no unit confusion.
- Scenarios: existing assumption editors, deterministic runs, revisions/results/quality and uncertainty display; no invented values, no unsupported input slider bounds.
- Alerts: existing rules/events/delivery states and permissions; clearly in-app analysis/monitoring, never automatic brokerage action.

Then propagate the same system across **every** observed route and detail surface. Account selector, command palette, Settings, saved layouts, sign-in, PWA, exports, reports, research, planner, quality/sources, premium-provider states and all error/partial/loading states must be included. Avoid isolated cosmetic patches with contradictory styles.

### 6. Financial, authorization and integration invariants

Preserve verbatim the permanent broker security model: default-deny; exactly the documented **ten typed Trading 212 GET capabilities**. Do not add order placement/cancellation/amendment, Pie mutations, CFDs, transfers, payment/deposit/withdrawal APIs, generic broker requests or arbitrary URL dispatch. Do not introduce Live/production access.

Preserve:

- Deterministic Decimal/NUMERIC financial calculations; explicit currency/timezone, UTC timestamps and calculation versions.
- Existing cash-flow, dividends, return, allocation and FX methods.
- Source timestamps, method/version, coverage, reconciliation, provenance and warnings.
- Distinct **missing, true zero, stale, partial, estimated, unreconciled, unavailable, failed and unresolved** states. Never replace unknown with zero or a confident-looking chart proportion.
- Authentication, owner/account scope, private data handling, source confidentiality, export contracts and permission-gated controls.
- All currently supported interactions, inputs, filters, pagination, deep links, downloads, job behavior and error handling.

Use only synthetic fixtures in screenshots and publicly shareable visual evidence. Never request, retrieve, expose, log, record or commit secrets, tokens, signed URLs, real private accounts or private financial contents.

### 7. Quality and regression plan

Deliver evidence, not a claim. Keep existing quality gates intact and run all relevant checks:

1. Frontend formatting, ESLint, strict TypeScript, Next.js build, shared UI package tests, generated API/contracts and architecture checks.
2. Existing React/Vitest component/unit tests and browser/API Playwright suites; preserve current fixtures and route behavior.
3. Relevant Python/backend security and contract negative cases when visual changes might touch request boundaries; confirm server/broker code and allowlist unchanged.
4. Theme selector, theme persistence, system switching, initial-paint correctness, light/dark chart styles, CSP and hydration behavior.
5. Accessibility: keyboard traversal, dialog focus, sticky-header focus visibility, contrast, target sizing, error announcements, accessible names, non-color state cues, reduced motion and zoom.
6. Responsive checks at representative desktop (~1440px), tablet (~768px), mobile (~390–432px), narrow 320px and 200% zoom. Ensure no page-level horizontal scrolling or hidden action controls.
7. Synthetic screenshots of **all six reference areas** in both themes and desktop/tablet/mobile; representative additional route/deep-page/empty/error states. Each screenshot must have exact route, viewport, fixture, SHA and outcome metadata.
8. Preserve and rerun applicable performance contracts including admission p95 ≤0.750s, read p95 ≤0.500s and ≤12 read SQL statements, browser LCP gates and any other then-authoritative thresholds, under unchanged source-qualified protocols. **Do not use UI redesign as a pretext to change these requirements.**
9. Check security scanner actual exit codes and finding classifications separately; a classified nonsecret finding is not a passing scanner. Record CI as disabled/unverified unless owner separately activates it.
10. Evidence manifest: exact commands, exits, timings, source SHA, dependencies, failing cases, bounded recoveries, hashes and explicit `passed`/`failed`/`pending_local`/`blocked_external` states.

Use serial task-local runtime checks and scope Docker cleanup to verified task-owned resources. Preserve original volumes, qualified images, historical evidence, source and dependencies. Do not delete unrelated files or perform broad pruning.

Do not weaken tests, lower coverage/performance targets, change security allowlists, bypass lint/type checks, mark skips as passes, erase failures, or combine results from different source revisions into a fabricated final-suite pass.

### 8. Commit discipline and truthful documentation

After each coherent, validated implementation batch, sync/re-read remote `main` and ensure no concurrent writer, then commit directly to `main` with a clear Conventional Commit message and fast-forward push. No branches, PRs, force-push, reset, rebase, amend or history rewrite.

Keep architecture/design docs, `CHANGELOG.md`, `PROJECT_STATUS.md`, `PROJECT_PROGRESS.json`, `VALIDATION_REPORT.md` and relevant acceptance/scenario records consistent with **what was actually implemented and independently eligible for review**. Do not mark Phase 3, UI redesign or P3-10 accepted on your own.

At completion provide:

- Starting and final live/local SHA; ordered commit list and exact changed-file manifest.
- Before/after route and feature coverage reconciliation; any missing UI area explicitly identified.
- Design tokens, theme initialization/persistence explanation, component/asset mapping and responsive decisions.
- Full test matrix with source-qualified passes, failures, pending checks, and security/CI status.
- Screenshot/evidence inventory (synthetic only), hashes, accessibility and performance qualifications, unresolved issues.
- Concise independent-review checklist and exact owner gates remaining for P3-10, CI, external providers, production and redistribution.

If a material failure persists, **STOP, REPORT INCOMPLETE, and preserve the evidence**. Do not declare the project closed. P3-10 execution, Live/production access, third-party credentials, CI activation, secret rotation, and binary/container redistribution require **separate explicit owner authorization**.

## END COPY-READY CODEX PROMPT

---

## Owner/reviewer usage note

Do **not** send this prompt while Checkpoint B is still incomplete or while another writer is modifying `main`. The completed 16 November Checkpoint B package still reports material failures. The reviewer may publish these three documents as draft planning artifacts **without** authorizing implementation. Once the owner separately accepts the applicable phase and approves the UI package, copy only the text between the BEGIN/END markers to Codex.

The UI modernization is a prerequisite to an aesthetically complete release **only if the owner chooses to include it in the release scope**. It is not a substitute for formal Phase 3/P3-10 acceptance or an authorization to use production credentials.
