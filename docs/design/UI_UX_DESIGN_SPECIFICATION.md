# Portfolio Intelligence — UI/UX Design Specification

**Status:** DRAFT FOR OWNER REVIEW — documentation publication does not mean design approval, implementation, or phase acceptance.
**Prepared:** 2026-11-16.
**Repository:** ntua-el21026/trading212-portfolio-intelligence.
**Reference code snapshot:** GitHub `main` at `74a406149aa47d3b8bbe709a07d63a0f588803ad`. The detailed frontend inventory was read at ancestor `7c2828a`; the seven-commit GitHub comparison confirms that the only subsequent frontend source edit was the account-selector navigation correction. Re-inventory whichever `main` is live before implementing.
**Design inputs:** the six supplied `Portfolio_Intelligence_Minimal_v2_*` PNG concepts, covering Overview, Holdings, X-ray, Performance, Scenarios, and Alerts.
**Scope:** a whole-product visual redesign, not a financial, API, security, or functional redesign.

## 1. Authority, evidence, and interpretation

1. This document is a **proposed additive visual specification**, subordinate to `AGENTS.md`, `docs/DESIGN_INDEX.md`, accepted design freezes/ADRs, broker allowlist, active phase manifests, and security/financial policies. Conflicts require owner resolution; this document never silently supersedes higher authority.
2. The six supplied screenshots are **synthetic design references**, not proof of live UI behavior, feature existence, numerical correctness, source coverage, or accessibility. Their financial values, dates, labels, statuses, and imagined controls cannot be copied as production facts.
3. Verified from the cited GitHub snapshot: `apps/web` uses Next.js 16.4.1, React 19.2.8, TypeScript, Recharts 3.10.1, Lucide React, application CSS/CSS modules, and `@trading212/ui` primitives. Existing shared UI elements include `Surface`, `Button`, `StatusPill`, `Notice`, `EmptyState`, and `Skeleton`. Current `apps/web/app/styles.css` supplies light-only semantic tokens and responsive breakpoints at 74rem, 58rem, 46rem, and 24rem. There is also a command palette, mobile navigation, and PWA runtime.
4. No claim is made that the visual design has been implemented or browser-tested. Re-confirm all framework versions, routes, constraints, and acceptance status against the future implementation SHA.

### Design goals

- Premium, calm, contemporary financial SaaS aesthetic; lightweight, information-dense, legible, and trustworthy.
- Consistent **light, dark, and system** themes; both themes are fully designed, not an inversion.
- Reusable primitives, centralized tokens, vector assets, accessible interactions, minimal added dependencies.
- Preserve all application features, exact financial semantics, quality/provenance, account authorization, and the permanent read-only Trading 212 boundary.
- Production screens must be driven by existing trusted data and contracts. Never fabricate values to emulate the screenshots.

### Explicit non-goals

- No new broker operations, trading, payments, order actions, Live activation, provider access, background polling, or generic HTTP tools.
- No change to authoritative Decimal/NUMERIC calculations, timestamp/currency contracts, permissions, quality states, or reported coverage.
- No backend, schema, migration, API, MCP, job or infrastructure changes unless an unavoidable dependency is independently justified and separately authorized.
- No new analytics feature or alert/scenario capability solely because a screenshot visually depicts it.
- No screenshots used as raster backgrounds, chart facsimiles, or page content.
- No marketing/public website, logo rebrand, or redistribution-license change implied by this package.

## 2. Mockup audit and visual interpretation

| Reference | Visual strength to retain | Functional/semantic caution |
| --- | --- | --- |
| 01 Overview | Typographic valuation hierarchy; large performance chart; lower allocation/holdings split | The summary cash amount differs from the allocation-ring cash amount; display only reconciled source values and available metrics |
| 02 Holdings | Dense but calm searchable table; micro-charts; selected-holding inspector | Do not assume every holding has historical price points, P/L, cost basis, or complete FX coverage |
| 03 X-ray | Exposure treemap; compact dimension tabs; explicit known/unknown coverage | Unknown/unresolved exposure must remain visible; the mockup's € totals can differ from the overview due to illustrative rounding |
| 04 Performance | Benchmark overlay; period controls; monthly return and drawdown panels | Benchmark and portfolio values must have compatible units, accounting methods, calendar, and source coverage |
| 05 Scenarios | Assumption panel and clear median/percentile outcome chart | Keep the existing model's permitted inputs, versioning, deterministic seed, uncertainty, caveats, and authorization; a mock slider is not a new backend feature |
| 06 Alerts | Scannable activity/status rows; rule editor; delivery status | Never imply an alert initiates broker actions; rule persistence, channels, and delivery claims must reflect implemented behavior |

### Reference palette sampling (not approved tokens)

Spot pixel samples from the Overview PNG include:

| Element / sample | Observed approximate pixel |
| --- | --- |
| Sidebar background | `#F6F7F7` |
| Canvas | `#FCFDFD` |
| Fine divider | `#E9ECEF` |
| Chart's green visual | `#028B65` |
| Very pale chart fill | `#F1FAF7` |

These are individual raster samples, **not** comprehensive color extraction. Antialiasing, gradients, image generation, and contrast requirements make production refinements necessary. For example, `#028B65` against white is approximately **4.30:1**, below the 4.5:1 target for ordinary text; use a darker green for textual UI.

## 3. Proposed design tokens

Token values below are **proposed production choices**, not observed exact source colors. Final tokens must be visually reviewed in both themes and measured against their actual layered backgrounds.

| Semantic token | Light | Dark | Meaning |
| --- | --- | --- | --- |
| `--pi-canvas` | `#FCFDFD` | `#10171B` | Page and shell background |
| `--pi-sidebar` | `#F6F8F8` | `#111A20` | Navigation surface |
| `--pi-surface` | `#FFFFFF` | `#172127` | Cards, menus, panels |
| `--pi-surface-raised` | `#FFFFFF` | `#1D2A31` | Modals, popovers, elevated panels |
| `--pi-surface-subtle` | `#F3F8F6` | `#1B302B` | Subtle fills, selection areas |
| `--pi-text` | `#0F1923` | `#F2F6F7` | Primary text |
| `--pi-text-secondary` | `#536577` | `#AEC1C9` | Secondary text |
| `--pi-text-disabled` | `#6C7C8B` | `#90A3AD` | Disabled text; still readable where necessary |
| `--pi-border` | `#DFE6E9` | `#34444B` | Standard borders and gridlines |
| `--pi-border-strong` | `#BAC8CE` | `#50636B` | Emphasized separators |
| `--pi-accent` | `#007C59` | `#54D6A5` | Links, primary accent, selected state |
| `--pi-accent-hover` | `#006C4E` | `#7AE6BD` | Interactive emphasis |
| `--pi-accent-wash` | `#E7F6EF` | `#17392F` | Selection and accent surfaces |
| `--pi-accent-foreground` | `#FFFFFF` | `#10291F` | Text on solid accent buttons |
| `--pi-positive` | `#087853` | `#54D6A5` | Positive quantities/confirmed success |
| `--pi-warning` | `#855600` | `#F1BE72` | Attention / pending / caution |
| `--pi-danger` | `#9D333B` | `#DC6E79` | Losses / errors / critical |
| `--pi-info` | `#205C96` | `#8BB6F7` | Informational states |
| `--pi-focus` | `#205C96` | `#8BB6F7` | Visible keyboard focus ring |

The proposed textual accent has an approximately **5.21:1** white-background contrast ratio; light secondary text approximately **6.01:1** on white. Dark primary text is approximately **15.9:1** against `#131C21` and dark accent approximately **9.3:1** against `#151E24`. These are spot calculations, **not a blanket conformance claim**.

### Theme CSS contract

Use centralized CSS variables, retaining compatibility with legacy variables such as `--color-navy`, `--color-emerald`, `--color-surface`, `--color-border`, and shared `@trading212/ui` styles while migrating consumers. Do not simultaneously maintain competing independent palette definitions.

~~~css
:root,
:root[data-theme="light"] {
  color-scheme: light;
  --pi-canvas: #fcfdfd;
  --pi-sidebar: #f6f8f8;
  --pi-surface: #fff;
  --pi-surface-raised: #fff;
  --pi-surface-subtle: #f3f8f6;
  --pi-text: #0f1923;
  --pi-text-secondary: #536577;
  --pi-text-disabled: #6c7c8b;
  --pi-border: #dfe6e9;
  --pi-border-strong: #bac8ce;
  --pi-accent: #007c59;
  --pi-accent-hover: #006c4e;
  --pi-accent-wash: #e7f6ef;
  --pi-accent-foreground: #fff;
  --pi-positive: #087853;
  --pi-warning: #855600;
  --pi-danger: #9d333b;
  --pi-info: #205c96;
  --pi-focus: #205c96;
}

:root[data-theme="dark"] {
  color-scheme: dark;
  --pi-canvas: #10171b;
  --pi-sidebar: #111a20;
  --pi-surface: #172127;
  --pi-surface-raised: #1d2a31;
  --pi-surface-subtle: #1b302b;
  --pi-text: #f2f6f7;
  --pi-text-secondary: #aec1c9;
  --pi-text-disabled: #90a3ad;
  --pi-border: #34444b;
  --pi-border-strong: #50636b;
  --pi-accent: #54d6a5;
  --pi-accent-hover: #7ae6bd;
  --pi-accent-wash: #17392f;
  --pi-accent-foreground: #10291f;
  --pi-positive: #54d6a5;
  --pi-warning: #f1be72;
  --pi-danger: #dc6e79;
  --pi-info: #8bb6f7;
  --pi-focus: #8bb6f7;
}
~~~

**Additional token families:** typography (`--pi-font-ui`, `--pi-font-mono`), spacing (4px base and 4/8/12/16/20/24/32/40/48), radii (6/10/14/20px and pill), border widths, elevation (none/subtle/popover), chart series, chart grid/axis/tooltip, motion durations (100/160/220ms), focus ring, and layout dimensions. Maintain the existing Inter/Segoe UI/system fallback, with no unlicensed or remote-required font.

### Visualization palette

| Series / meaning | Light | Dark |
| --- | --- | --- |
| Portfolio primary | `#008A63` | `#54D6A5` |
| Benchmark secondary | `#4D78B5` | `#8BB6F7` |
| Auxiliary series 1 | `#8E71C5` | `#B5A0E8` |
| Auxiliary series 2 | `#B26A33` | `#E8AC78` |
| Negative drawdown | `#C04750` | `#EC858E` |
| Grid | `#E7ECEF` | `#34444B` |
| Unknown / unresolved | `#90A0AF` | `#8799A4` |

Series must also differ by label, dash/pattern or marker where color is insufficient. Do not use one red/green encoding for all risk, quality, and market states. For chart geometry, existing Number conversion is permissible only after canonical Decimal values are already determined; displayed figures remain exact contract-backed strings.

## 4. Typography, spacing, and layout

| Element | Desktop target | Mobile target | Notes |
| --- | --- | --- | --- |
| Page H1 | 34–42px, 650–750 | 28–34px | Balanced line height, avoid oversized headlines |
| Section H2 | 20–25px, 600–700 | 19–22px | Compact but visually distinct |
| KPI dominant | 32–44px, 650–750, tabular numerals | 28–38px | Long currencies must wrap or scale, never clip |
| Body | 14–16px | 14–16px | Text density informed by financial workflow |
| Table | 13–14px | 13–14px | Right-align quantities; use tabular numerals |
| Supporting labels | 12–14px | 12–14px | Do not make essential provenance microtext |
| Sidebar | 240–256px expanded | Drawer/section menu | 22 destinations need grouping and discoverability |
| Topbar | 64–72px | 56–64px | Retain account/authorization context |
| Content padding | 24–36px | 16–20px | 12-column responsive grid, 16–24px gaps |
| Detail inspector | ~300–360px | Stacked/drawer | Never obscure data or keyboard focus |

Use restrained rounded corners (approximately 10–14px cards, 8–10px inputs), primarily thin borders, and barely perceptible elevation. Avoid heavy glassmorphism, ornamental gradients, glow effects, animated financial numbers, and excessive chart effects.

### Responsive behavior

- **Large desktop (≥1184px):** anchored navigation plus multi-column content; optional side inspector; charts take available width.
- **Compact desktop/tablet (736–1183px):** narrower/collapsible navigation; 2-column metrics as appropriate; no overlapping chart legends or filters.
- **Mobile (≤735px):** stacked KPIs, drawers for inspectors, one-column content, compact chart controls, accessible section navigation. Retain reachability of **every** destination, not only the existing five bottom-nav shortcuts.
- **Small mobile / 320 CSS px / 200% zoom:** content reflows; tables may scroll in named, keyboard-accessible regions with visible affordance and preserved sticky identifiers where feasible; no global horizontal page overflow.
- Respect safe-area insets, existing focus-reveal behavior, reduced motion, browser zoom, landscape and high-DPI settings.
- Preserve the existing route compilation and mobile navigation functionality; breakpoint values above are design intentions, not authorization to rewrite existing layout mechanics without tests.

## 5. Theme behavior

1. Theme preferences: `light` / `dark` / `system`, default `system` for new users unless an accepted product decision dictates otherwise.
2. Preference must persist locally (cookie or localStorage) without requiring new backend endpoints, identity scopes, or network access.
3. Resolve the correct theme before meaningful first paint. Choose a CSP-compatible bootstrap strategy after inspecting Next.js, CSP and authorization boundaries; do not insert an unsafe inline script just to hide flashing.
4. `system` follows operating-system changes dynamically; an explicit selection overrides it until changed.
5. Apply `data-theme` (or the existing stack's equivalent) at a consistent root and synchronize native `color-scheme`, form controls, scrollbar, SVG strokes and PWA theme-color where supported.
6. Theme selection belongs in Settings and may be accessible from the shell. It must have accessible labels and keyboard operation, and should survive navigation, refresh, account switching and sign-out without disclosing account data.
7. All popovers, dialogs, exported screen previews and charts must derive colors from the active theme; avoid stale server-render/client-hydration mismatches.

## 6. Shared component requirements

| Family | Required behavior |
| --- | --- |
| Application shell | Preserve selected account, demo/Live labeling, read-only notice, synchronization status, skip link, keyboard navigation and command palette; restyle instead of replacing navigation logic |
| Navigation | Keep all current routes and deep links; visually organize long menus without making pages undiscoverable; preserve account-scoped query routing |
| Page header | Consistent title, description, actions and responsive wrapping |
| Metrics | Label, value, currency/unit, timestamp, methodology/coverage warnings and availability states; meaningful visual hierarchy |
| Cards/panels | One shared system for elevation, border, headings, spacings, loading/empty/error states |
| Data tables | Sorting/filtering/pagination only where already supported; horizontal-scroll affordance; visible focused row/actions; exact financial alignment; consistent accessible column labels |
| Charts | Existing Recharts/chart components wherever suitable; accessible summary/table alternative; correct units/tooltips; chart series theme tokens; no generated fake data |
| Forms/controls | Input/select/slider/buttons/tabs/drawers/dialogs with consistent focus/error/help/disabled states; existing validation and domain bounds unchanged |
| Feedback | Clearly differentiated success, warning, danger, info, unavailable and pending; never rely on color alone |
| Export/download | Preserve exact format, authorization, filename, job status and content integrity; UI changes cannot alter export bytes by accident |
| Settings/PWA | Preserve sign-in/out, account selection, saved layouts, provider state and PWA/offline security semantics |

### Mandatory data-state presentation matrix

| State | UI requirement |
| --- | --- |
| Known/reconciled/fresh | Normal value plus provenance and scope when relevant |
| Missing | Show an explicit dash or “Missing”; **never 0** |
| Zero | Show actual zero with currency/unit when provided |
| Stale | Visible “Stale” and last known/source timestamp; avoid false freshness |
| Partial | Coverage percentage and affected inputs or periods where available |
| Estimated | “Estimated” label and method/assumption link where available |
| Unreconciled | Warning state and discrepancy explanation/drill-down |
| Unavailable | Clear “Unavailable” plus reason/retry if existing |
| Failed | Error state with traceable retry/support path where existing |
| Unresolved/unknown exposure | Explicit residual in charts and totals, never silently assigned proportionally |
| Loading/pending | Skeleton or progress semantics without invented outcome or misleading completion |

## 7. Real route and component coverage (snapshot)

At the inspected SHA, `apps/web/components/navigation.tsx` lists **22 primary destinations** and Settings. Page files additionally contain detail and specialized routes. This inventory must be regenerated from live `main` before implementation.

| Design workstream | Current observed destinations |
| --- | --- |
| Core portfolio | `/`, `/holdings`, `/holdings/[positionId]`, `/allocation`, `/activity`, `/dividends`, `/snapshots`, `/synchronization` |
| Trust and sources | `/quality`, `/sources`, `/sources/benchmarks/[definitionId]`, `/sources/snapshots/[kind]/[snapshotId]` |
| Allocation and planning | `/pies`, `/pies/[portfolioId]`, `/drift`, `/planner`, `/planner/[planId]`, `/aggregation`, `/income` |
| Analytics and intelligence | `/performance`, `/risk`, `/scenarios`, `/projections`, `/research`, `/xray`, `/xray/sources/[snapshotId]` |
| Reporting and alerts | `/reports`, `/reports/premium`, `/alerts` and current exported-artifact download flows |
| Shell and preferences | `/settings`, `/settings/layouts`, `/sign-in`, account selector, command palette, error/loading boundaries and PWA |

Use route/component names as a **coverage checklist**, not a mandate to invent features or reorganize information architecture without understanding existing flows.

## 8. Screen-specific visual contracts

### Overview

- Hero valuation should be readable first; secondary metrics on a single baseline when room permits.
- Only show a historical curve when supported by canonical snapshots/performance coverage. Otherwise use existing unavailable/limited states.
- Prefer a large chart plus balanced allocation/holdings cards as in reference 01, while retaining existing `QualityBanner`, `TrustRail` and reconciliation entry points.
- Always show reporting currency, valuation timestamp and quality context; never let chart polish override trust warnings.

### Holdings

- Dense table, optional existing search/filters and selected-row inspector; sticky headers if consistent with keyboard scrolling.
- Respect account selection, pagination, position details, currencies, FX, unresolved prices and available cost/P&L fields.
- Sparkline only where genuine source history exists; otherwise omit or show explicit insufficiency.
- Preserve all current row destinations/actions.

### Portfolio X-ray

- Use theme-aware treemap/bars for sector, geography, asset class and currency **only when actual underlying breakdown data supports the dimension**.
- Show known/unresolved and freshness separately; preserve retained-source detail navigation, methodology and publication/coverage constraints.
- Never visually close a 100% allocation by hiding unknown constituents.

### Performance

- Clear period controls, comparable portfolio and benchmark series, returns and drawdown where source-qualified.
- Axis and tooltip units must be explicit: do not put a return percentage and account value on one unlabeled scale.
- Retain TWR/MWR methodology, external cash-flow accounting, benchmark definitions, valuation cutoffs and negative outcomes.

### Scenarios and projections

- Reuse existing scenario and projection workflows: input/assumption editing, run status, asynchronous jobs, saved results, revisions and model caveats.
- Sliders may supplement existing validated controls, never replace precise numerical entry or constrain ranges arbitrarily.
- Use differentiated median/percentile bands and exact labels for methodologies, durations, units and confidence/coverage caveats.
- Keep “model output, not a forecast” language where appropriate to supported model semantics.

### Alerts

- Visual hierarchy for active rules, events, warning levels, stale source data and delivery state.
- Rule creation/editing and channels must follow real permissions and existing supported fields.
- Preserve in-app monitoring vs external notifications distinctions and default-deny provider/broker behavior.

### Additional existing areas

Apply the same shell, typography, tokens, cards, tables, charts, form controls and states to allocations, activity, dividends, snapshots, synchronization, quality, Pies, drift, planner, sources, risk, projections, research, aggregation, income, reporting, premium reporting, Settings, saved layouts, PWA, sign-in, all details, modals and error boundaries.

## 9. Accessibility and interaction acceptance

- Target **WCAG 2.2 Level AA** for applicable UI. Verify text contrast ≥4.5:1 (ordinary text), essential non-text indicators/controls ≥3:1 against adjacent colors, and pointer targets ≥24×24 CSS px or compliant spacing exceptions. Prefer a comfortable 40–44px control height for touch.
- Keyboard access to all routes, dialogs, tabs, menus, tables and form controls; visible focus; no keyboard traps except properly managed modal focus.
- Keep focus visible even with sticky topbar/mobile navigation; preserve existing `revealFocusedControl` protections.
- Semantic headings/landmarks and accessible names; avoid treating a chart image alone as the only source of numerical truth.
- Errors must include explicit text, correction guidance and relationship to fields; positive/negative colors accompanied by signs/text/icons.
- Respect `prefers-reduced-motion`, user zoom and text resizing; avoid animation-dependent information.
- Test theme variants with browser automation and manual screenshot review; visual screenshots cannot prove accessibility conformance.

W3C references:
- https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum
- https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast
- https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum
- https://www.w3.org/WAI/WCAG22/Understanding/focus-not-obscured-minimum

## 10. Validation and acceptance criteria

The future UI package is **not accepted** until each applicable requirement is evidenced against the same immutable UI implementation SHA. At minimum:

1. Route inventory and functional before/after mapping covers every live route and meaningful state; no orphaned navigation or removed capability.
2. Light, dark and system themes initialize correctly; persist through refresh, account changes and navigation; no initial incorrect-theme flash under the tested CSP.
3. All six visual references are recognizable as a coherent style, with documented deviations for actual behavior and data truth.
4. Desktop, tablet, mobile and 200%-zoom flows have no blocking overlap/clipping, inaccessible controls or globally overflowing page.
5. All user-facing chart labels, values, currencies, percentages, timestamps, quality and provenance retain authoritative semantics.
6. Keyboard and automated accessibility checks pass agreed gates; any independently observed exceptions are recorded as unresolved, never ignored.
7. Existing unit, browser, contract, architecture, security, performance, docs and build gates are not weakened, deleted, or silently waived.
8. The Trading 212 exact ten typed GET allowlist and default-deny boundaries remain unchanged.
9. Synthetic-only screenshot evidence is retained for representative routes in both themes and all three viewport classes, with exact command, SHA and artifact checksums.
10. Final acceptance is an independent owner/reviewer decision, **not** a Codex self-declaration. CI and external providers remain separately gated.

## 11. Asset and dependency strategy

- Reuse `lucide-react` for iconography; add SVG only for genuinely unique illustrations and sanitize SVG assets.
- Reuse Recharts 3 and current chart implementations. Prefer CSS/SVG over raster; do not embed mockup PNGs.
- Do not load remote fonts, icon scripts or dashboard templates by default; check redistribution rights before any newly introduced asset.
- Keep critical CSS and tokens first-party; preserve hydration performance and avoid new heavyweight UI libraries unless justified by measured need.
- Respect `LICENSE.md`: source-publication rights do not automatically grant permission to redistribute dependency binaries, Docker images, fonts or third-party artwork.

## 12. Review status and next step

This document is ready for owner review as a **non-authoritative design proposal**. It may be committed to `docs/design/` solely as planning documentation after the completed Codex package is independently checked for a safe repository handoff. Its presence on `main` does not approve implementation.

The newly reported Checkpoint B has material unresolved admission, pending-navigation Back, configured SAST, Web repeatability and cumulative native coverage issues. No visual redesign work may begin until the owner/reviewer independently accepts the necessary preceding phase gate and separately authorizes the UI package.

The accompanying roadmap defines phase gates. The accompanying Codex prompt is a **future-use candidate**; it cannot itself mark Checkpoint B accepted, authorize P3-10, or override security/financial requirements.
