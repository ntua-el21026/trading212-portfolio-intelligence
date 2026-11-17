# Portfolio Intelligence — UI Redesign Implementation and Closeout Roadmap

The original design and planning text below records its cited preparation snapshot.
It is retained as development provenance, not as a current implementation plan.
For the accepted result, see the [architecture freeze](../DESIGN_FREEZE_LOCAL_DEMO_20261117.md),
[owner acceptance](../implementation/LOCAL_DEMO_ACCEPTANCE_20261117.md) and
[implementation report](../implementation/LOCAL_DEMO_IMPLEMENTATION_20261117.md).
No further UI implementation is authorized by this historical document.

**Status:** Historical planning record; implemented LOCAL/DEMO milestone accepted on 17 November 2026.
**Current authority:** [Owner-authorized scope](../implementation/LOCAL_DEMO_SCOPE_20261117.md). Earlier snapshots below are historical.
**Prepared:** 2026-11-16.
**Related:** `UI_UX_DESIGN_SPECIFICATION.md` and `UI_REDESIGN_CODEX_PROMPT.md`.
**Live snapshot inspected:** `main` `74a406149aa47d3b8bbe709a07d63a0f588803ad`. Earlier detailed frontend inspection used ancestor `7c2828a`; the subsequent diff was inspected and does not alter the enumerated route structure. Recheck the live SHA before any later implementation.

## 1. Why this is a separate package

The completed Phase 3 Checkpoint B report explicitly remains **INCOMPLETE**. The uninstrumented admission p95 is **0.832402193 seconds** against **0.750**; pending-navigation Back fails across desktop/tablet/mobile; configured SAST exits 3; Web repeatability reports 271 content/type/mode differences; cumulative native coverage remains pending. Historical aggregate suites retain their failures. All 30 Phase 3 acceptance rows and 48 scenarios remain pending, zero accepted; P3-10 is not started, and CI is owner-deferred. These are **reported results corroborated in published status documentation**, not independently rerun tests. **None of the design work below resolves or waives those existing gates.**

The proposed UI modernization is a visually extensive but behavior-preserving change. It is not automatically included in a previously frozen Phase 3 baseline. The owner has now explicitly authorized its LOCAL/DEMO implementation while Checkpoint B remains INCOMPLETE.

## 2. Gate sequence

| Gate | Entry evidence | Exit/decision |
| --- | --- | --- |
| G0 — Design preparation | User's six mockups and design brief; read-only GitHub architecture inspection | Three draft documents prepared; no repository mutation |
| G1 — Running Codex handoff | Codex posts final output; current live/local `main` rechecked | Independently classify actual tests, security, performance, migrations, docs and failure receipts |
| G2 — Checkpoint B disposition | Applicable full qualification and unchanged performance contract reviewed | Explicit Checkpoint B accepted, or retain INCOMPLETE; **current state is INCOMPLETE** |
| G3 — Design document commit | Owner's advance instruction to publish after Codex finishes, plus safe synchronized `main` | One docs-only linear commit to `main` after repository and authority checks; files remain DRAFT and do not alter G2 |
| G4 — UI implementation authorization | Explicit owner LOCAL/DEMO authorization recorded; financial/security authority preserved | A future Codex prompt may be executed; no P3-10, CI or provider authority implied |
| G5 — UI implementation and qualification | Clean synchronized `main`, confirmed ZIP, complete route map and fixed tests | Targeted LOCAL/DEMO visual/functional/security/build evidence; original phase gates retained separately |
| G6 — Independent UI review | Final SHA, receipts, screenshot matrix, complete test artifacts | Accept, reject or require scoped remediation |
| G7 — P3-10 and project closeout | Separate explicit owner P3-10 authorization and all applicable prior gates | Release-candidate qualification and independently recorded acceptance; external gates reported honestly |

**Safety rule:** G3 is an independent, documentation-only planning action and may occur while G2 remains INCOMPLETE. **G4/G5 are now authorized for LOCAL/DEMO only**, independently of G2, by the current owner instruction. Do not represent documentation publication as Checkpoint B acceptance. If the new design conflicts with accepted freeze documents, hold G3 until the owner approves a compatible additive clarification.

## 3. Prepared-document placement after the Codex handoff

Intended repository locations for the documentation-only publication:

| Staged file | Planned location on `main` |
| --- | --- |
| `UI_UX_DESIGN_SPECIFICATION.md` | `docs/design/UI_UX_DESIGN_SPECIFICATION.md` |
| `UI_IMPLEMENTATION_ROADMAP.md` | `docs/design/UI_IMPLEMENTATION_ROADMAP.md` |
| `UI_REDESIGN_CODEX_PROMPT.md` | `docs/design/UI_REDESIGN_CODEX_PROMPT.md` |

Before a docs-only commit:

1. Read the latest Codex report and compare its claims to live GitHub `main`, active docs, tests/evidence where accessible and any owner-deferred gates.
2. Confirm exactly one `main` branch, the expected head SHA, and a clean local worktree; do not create another branch or rewrite history.
3. Read `AGENTS.md`, `docs/DESIGN_INDEX.md` and applicable accepted freeze/ADR documents. Re-check current `apps/web` routes, stack and component boundaries; update these draft files if reality differs from their versioned snapshot.
4. Reconcile overlapping docs: `docs/DESIGN_INDEX.md` may receive a **non-authoritative reference** to `docs/design/` if consistent with existing governance. Do not alter accepted phases, acceptance ledgers or claims of implementation merely to add this proposal.
5. Validate Markdown, links, JSON status compatibility if touched, and `git diff --check`. A docs-only change should not require backend changes.
6. Commit with one coherent Conventional Commit message (suggested: `docs(ui): add gated frontend redesign handoff`), push fast-forward to `main`, verify live file bytes/head, and report the SHA. If head advanced during editing, reread and integrate before any commit.
7. Do not activate CI, access broker credentials, run Live/production, or distribute images/binaries.

## 4. Future bounded implementation packages

These are **logical execution batches**, not extra Git branches or independent phase authorizations. Codex may create coherent linear `main` commits as each batch is validated, provided the owner has authorized G4 and the app remains runnable at every commit.

### U0 — Source and route baseline

- Fetch live `main`, inventory routes/detail routes, permission states, query parameters, navigation, CSS modules, charts, PWA and tests.
- Record source SHA, environment, approved CSS conventions and baseline synthetic screenshots for representative flows.
- Validate the ZIP from the actual Windows Downloads folder (WSL mount if appropriate), count six PNGs, extract safely into a task-local temporary directory; do not commit them.
- Create a source-to-mockup mapping; note that only six references exist for more than 20 primary pages.
- Review CSP, Next.js 16 local docs, theme init, authentication and chart SSR/hydration constraints.
- **No implementation until U0 inventory is reviewed for incompatible assumptions.**

### U1 — Shared design tokens and themes

- Add centralized semantic tokens in the existing styling architecture and bridge legacy variables.
- Introduce light/dark/system selection and CSP-safe flash-free initialization without backend preference dependency.
- Update shared `@trading212/ui` primitives before individual pages.
- Verify contrast ratios, focus, disabled/empty/error styles, theme persistence, chart palettes, visual regression in both modes.
- No financial/API/contract changes.

### U2 — Shell and navigation

- Modernize `AppShell`, sidebar, topbar, account picker, read-only/demo labels, command palette, and responsive navigation.
- Preserve all links, query and account context, PWA safe-area, skip link and focus reveal.
- Ensure the 22 primary routes at the inspected snapshot remain discoverable on desktop, tablet and mobile.
- Check keyboard navigation, account-switching, command-palette focus and sign-out behavior.

### U3 — Six reference areas

1. Overview — valuation hierarchy, actual historical/coverage states, allocation/holding summaries.
2. Holdings — data table, existing filters, detail route, optional real-history sparklines.
3. X-ray — exposure panels/treemap, coverage and unresolved residuals.
4. Performance — period/benchmark chart, cash-flow and methodology context.
5. Scenarios — existing form/job/results, percentile or other supported outcome display.
6. Alerts — monitored activity, existing rule editor, status and delivery surfaces.

Implement each with shared tokens, small reviewable commits and direct regression tests. Do not copy illustrative numbers or create unsupported functionality.

### U4 — Remaining application coverage

- Allocation, activity, dividends, snapshots, synchronization, quality, Pies, drift, planner, sources, risk, projections, research, aggregation, income, reports/premium, Settings, layouts, sign-in, all nested/detail pages, loading and error boundaries.
- Update deep-page tables, complex forms, outputs, export/download status, selectors, tooltips, PWA and permission-gated states.
- No page may retain broken legacy foreground/background pairings in dark mode.
- Keep the source-of-truth financial status models and existing interactions intact.

### U5 — Responsive and accessibility qualification

- Cover viewport classes representative of desktop (~1440px), tablet (~768px), mobile (~390–432px), a narrow 320px case, and 200% zoom/reflow.
- Test keyboard-only paths, screen-reader semantics by DOM assertions/manual review, focus visibility, target sizing, reduced motion and error recovery.
- Compare screenshots to the supplied visual references where appropriate; screenshots are **inspiration**, not pixel equality or functional truth.
- Check both themes and system preference; verify theme initialization before first meaningful paint.

### U6 — Exact implementation-source validation

- Record the exact implementation source. Run targeted LOCAL/DEMO formatting, lint, strict typing, generated-contract, architecture, security-critical, unit, build, documentation and representative browser/API checks. Complete multi-hour suites require renewed owner approval; record them NOT RUN. Original Phase 3 requirements and failed gates remain unchanged.
- Re-run any failures after correction **without hiding original failure receipts**. If source changes, previous passing evidence is not silently promoted to final-SHA qualification.
- Test actual data-quality states, authorization boundaries, exact ten GET allowlist, account scoping, exports and read-only broker behavior.
- Run browser visual matrix in light/dark across desktop/tablet/mobile using synthetic fixtures only. Capture route, viewport, theme, timestamp, SHA and artifact hashes.
- Preserve resource ownership and privacy; do not delete unowned volumes, images, state, evidence archives or work.

### U7 — Documentation, independent review and closure

- Update implementation report, status/progress, validation report, acceptance/scenario records and changelog **only to the degree they are actually affected**. Record unexecuted checks as pending, not passed.
- Provide review-ready report: exact commits, changed files, validation matrix, regression evidence, theme/screenshots, accessibility risks and remaining blockers.
- Independent reviewer compares final GitHub code to the claims and approves/holds the UI package.
- P3-10, CI activation, credentialed providers, Live, production and redistribution are **distinct owner gates**. Never self-authorize them or report project closure solely because the UI appears polished.

## 5. Test and evidence matrix

| ID | Required check | Evidence |
| --- | --- | --- |
| UI-01 | Every route retains functional entry and navigation | Route inventory, link/deep-link tests |
| UI-02 | All current forms, filters, selectors and job actions work | Relevant existing and updated unit/E2E tests |
| UI-03 | Auth and account scoping preserved | Signed-out, wrong-account, no-permission and account-switch cases |
| UI-04 | No change to broker allowlist or any broker write | Architecture/negative tests and diff |
| UI-05 | Financial values/units/quality preserved | Exact contract fixture comparisons and rendered assertions |
| UI-06 | Light/dark/system switching and persistence | Theme unit tests and first-paint/browser assertions |
| UI-07 | Desktop/tablet/mobile reflow | Screenshot matrix and overflow assertions |
| UI-08 | Keyboard/focus/contrast/target size | Automated a11y and manual evidence |
| UI-09 | Charts are responsive, semantically correct and theme-aware | Chart tests, visual screenshots, unit/tooltip checks |
| UI-10 | Loading/partial/stale/unavailable/error paths render honestly | State fixture tests and screenshots |
| UI-11 | Exports/downloads, report navigation and paginated collections retained | Existing E2E/negative tests |
| UI-12 | Web build/type/lint/format and targeted LOCAL/DEMO suites | Exact commands, exit codes, durations, source manifests |
| UI-13 | Performance is not degraded and historical gates remain unchanged | Targeted browser observations and historical performance limitations; no new full admission experiment or altered thresholds |
| UI-14 | Security/scanner findings and CI reported truthfully | Scanner exits/findings classification, statuses/workflows and owner gate |
| UI-15 | New SVG/assets and dependencies have redistribution rights if shipped | Asset/dependency license inventory |

For unfinished items use explicit `pending_local`, `failed`, or `blocked_external` only when the latter is a genuinely external prerequisite. “Reviewed nonsecret” is a classification, not a green scanner exit.

## 6. Resource and security safeguards

- Synthetic-only display evidence; never include real financial screenshots, account identifiers, cookies, tokens, private-provider responses, or signed download links.
- Work in one scoped task stack, serializing heavy browser/database checks on the laptop. Do not modify unrelated Compose projects.
- Before cleanup, inspect exact owned containers/volumes/networks and verify task backups when required. Preserve external/unowned resources, qualified images, dependencies, historical receipts and current repositories.
- Preserve published migrations and dependency locks unless a separately approved change is justified. UI-only work should not need schema edits.
- Keep all three existing workflows disabled until the owner separately authorizes CI.

## 7. Final project-closeout definition

Three statements must remain distinct:

1. **UI modernization complete:** the approved UI package has complete passing local evidence at an immutable SHA and has been independently accepted.
2. **Phase 3 / P3-10 complete:** the separate active phase's 30 acceptance rows and 48 scenario records meet their actual authority, P3-10 is owner-authorized/executed, and independent acceptance is documented.
3. **Production/distribution ready:** provider access, Live credentials, CI, deployment, secret renewal, licensing and binary/container rights have separate explicit owner sign-offs.

Completion of (1) does **not** imply (2) or (3). The final Codex prompt must stop and report any failed prerequisite instead of converting it to a success claim.

## 8. Handoff checklist for the owner/reviewer

- [ ] Codex final checkpoint report received.
- [ ] Live GitHub `main` and local worktree independently checked.
- [ ] Source snapshot and route inventory in design spec refreshed.
- [ ] Checkpoint B reported status and immutable evidence independently reviewed.
- [ ] Three design documents approved as accurate *planning* artifacts.
- [ ] Docs-only fast-forward commit completed and verified, with no implicit phase acceptance.
- [ ] Separate UI implementation authorization issued after applicable gates.
- [ ] UI implementation, full qualification and independent acceptance completed.
- [ ] Separate P3-10 authorization/qualification and project-closeout decisions completed.
