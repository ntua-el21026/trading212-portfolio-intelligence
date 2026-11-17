# LOCAL/DEMO route coverage — 17 November 2026

The final implementation is `e1e8da74846d9a248740bbf7560ea9b7183b32bc`.
Its supplement to the broader UI baseline changes one production `aria-label`
attribute and one regression. The compact selector's original 320-pixel failure,
14 passing affected theme tests and 12 passing viewport/theme combinations are
retained under `narrow-theme-accessibility`, `compact-theme-unit-red`,
`compact-theme-unit-recovery` and `compact-theme-browser-recovery`. The larger
observations below remain tied to their actual earlier manifests; all formal
Phase 3 items remain pending.

**Owner:** Michail Athanasios Peppas. This record implements the
[LOCAL/DEMO scope](LOCAL_DEMO_SCOPE_20261117.md) with existing routes, components,
forms and backend capabilities. The owner authorized representative checks based
on risk; the complete historical browser matrix was not rerun. Checkpoint B remains
INCOMPLETE: all 30 Phase 3 rows and 48 scenarios remain pending, zero accepted.

The broader browser observations bind base `0487425dd81e42f735dbe6376f8d7fa9fe9281b6`
and working-code manifest
`15c0bee3663ac15a87212809b8c4e0141d19e8b6074c70145951a8b7d3aa2172`.
Implementation commit `65d1d0db8bc9b8bb2682bc74b73cdcd4c5828ffc` contains byte-equivalent application code (1,709 paths verified in the private equivalence record). These are pre-commit executions, not same-SHA reruns. Receipt names below are
logical references to retained owner-private evidence, not repository artifacts.

## Evidence and interpretation

A final affected invocation passes 54 tests in nine files at the final browser
manifest (`final-affected-web-units/receipt.json`, exit 0, 2.047 seconds). Its scope
is theme SSR/client state, navigation, account masking, allocation, snapshot and
historical charts, overview and financial currency presentation; U retains its
own earlier full-unit source binding.

| Key | Actual observation and retained receipt |
| --- | --- |
| D | `demo-visual-final-recovery/results.json`: PASS, 150 views of 25 routes across desktop, tablet and mobile in light and dark; 38 deliberate auth-free Demo captures; zero page or console errors. |
| F | The same completed protocol exercises sign-in, skip-link keyboard focus, navigation, holdings filtering, cursor pagination and native Back, holding detail, Settings and sign-out. System preference tracks OS changes and persists after reload. No-JavaScript sign-in checks cover saved light, dark and system choices before hydration. Holdings also has representative 320-pixel and 200% CSS-magnification stress checks; native browser zoom was not measured. |
| A | `local-api-research-ui-fresh-v2/receipt.json`: exit 0 in 119.069 seconds; `local-api-smoke-O2JucT/receipt.json`: all three authenticated viewport journeys and subsequent denial stages passed. Each journey explicitly selects the retained research item, historical owner-note revision and review acknowledgment, then submits the real four-format form and waits for worker success. Twelve browser downloads match status SHA-256 and size; JSON source-value checks and the independent CSV/XLSX/PDF inspector pass. |
| U | `frontend-units/receipt.json` and `frontend-units/output.log`: exit 0, 980 cases in 112 files. This run has its own earlier working-source manifest `ce18e6c3056698f5cd93bf0adaa30275e0764907c3b45c8969655d529d8b89e4`; it is not relabeled as a new execution at the final browser manifest. |
| S | Current source and shared theme/component review, supported by the named regression contracts within U. No new browser execution of that deep route is claimed. |

D uses desktop 1440×1024, tablet 768×1024 and mobile 390×844; A uses desktop
1440×900 and the same tablet/mobile sizes. The 150 views cover 25 distinct page
paths. Sign-in and one holding detail add two exercised paths, giving **27 of the
32 page-route patterns**. The remaining five deep routes have S coverage. The
38 captures comprise six reference areas across both themes and all three devices,
plus the two holdings reflow captures; they are not 38 additional routes.

A also passes one real offline submission with preserved exact choices and retry
identity, account-switch masking with dark preference retained, cross-account and
foreign/missing-note denial, revoked report/download denial, expiry and revoked
write denial. Fixture controls run after all three positive journeys. A records no
authenticated screenshots, HTML, traces, videos or assets; intended synthetic report
artifacts and closed metadata were retained. `browser-privacy-canary-v2/receipt.json`
records the public-invalid-input qualification, including explicit capture refusal,
of that helper pipeline. The historical Playwright capture/reporting matrix was
not qualified by this run.

The original failed `local-api-research-ui/receipt.json` and
`local-api-smoke-WTIqeS/receipt.json` remain failures before report admission.
The selected-item read later returned 503 after the fixture's ten-minute retained
source lifetime had elapsed. Source expiry remains a strong orchestration inference;
the exact returned error enum was not verified. Fresh-fixture success is a separate
observation, and the original failed result remains retained.

## All 32 page routes

Every row retains its existing feature and applies the shared semantic palette,
responsive shell, forms, tables, focus treatment and light/dark/system theme.
**G** means `apps/web/app/styles.css` plus `packages/ui/src/styles.css`; additional
style names identify existing component CSS Modules. Components are under
`apps/web/components`; regression test stems are under `apps/web/tests` with their
existing `.test.ts` or `.test.tsx` suffix. Named contracts indicate relevant tests,
not per-route coverage percentages or additional browser executions.

| Route | Retained feature / component | Style | Regression contracts | New evidence |
| --- | --- | --- | --- | --- |
| `/` | Canonical totals, direct allocation and holdings preview; `overview`, `financial`, `charts`, quality rail | G, number-value | overview; financial-currency; allocation-color-correspondence | D, F |
| `/holdings` | Search, filters, paged positions and detail links; `portfolio-tables`, `collection-pagination` | G, number-value | collection-query; collection-pagination; financial-currency | D, F |
| `/holdings/[positionId]` | Original quantities, prices, declared currencies and methodology; `financial`, `quality` | G, number-value | financial-currency; number-value | F: one synthetic detail on each device |
| `/allocation` | Direct weights, cash, exact table and donut; `charts`, `financial` | G, number-value | allocation-color-correspondence; snapshot-chart | D |
| `/activity` | Transaction filters, flow classification and cursor pages; `portfolio-tables` | G, number-value | collection-query; collection-pagination; historical-ui | D |
| `/dividends` | Income records, canonical currencies and missing quantities; `portfolio-tables`, `financial` | G, number-value | financial-currency; collection-query | D |
| `/snapshots` | Immutable observations, disconnected gaps and exact source table; `snapshot-chart`, `portfolio-tables` | G, snapshot-chart | snapshot-chart; collection-pagination | D |
| `/synchronization` | Read-only refresh request and durable status; `refresh-control` | G | refresh-control; refresh-route | D |
| `/quality` | Reconciliation, discrepancies, source quality and paging; `quality`, `intelligence-quality` | G, intelligence-quality | quality-navigation; intelligence-quality-query | D |
| `/pies` | Internal target portfolios and creation form; `target-forms` | G | target-create-form; target-client | D |
| `/pies/[portfolioId]` | Versioned target editing, ordering and validation; `target-editor`, `target-forms` | G | target-editor; target-editor-order | S |
| `/drift` | Selected target/capture drift and company context; `planning-selection`, `planning-results`, `planning-company` | G | planning-company-query; planning-results | D |
| `/planner` | Manual contribution-plan inputs, selectors and results; `planning-form`, `planning-results` | G | planning-form; planning-actions; planning-results | D |
| `/planner/[planId]` | Saved plan revisions, status and result pages; `planning-job-status`, `planning-results` | G | planning-revision; planning-job-status; planning-results | S |
| `/sources` | Source collections, provenance and owned benchmark definitions; `source-details`, `benchmark-form` | G | source-pages; source-actions | D |
| `/sources/benchmarks/[definitionId]` | Owned benchmark version form and history; `benchmark-form`, `collection-pagination` | G | source-pages; source-actions; source-client | S |
| `/sources/snapshots/[kind]/[snapshotId]` | Exact price/FX/benchmark observations and source/license details; `source-details`, `composite-source-details` | G | source-pages; source-detail-account | S |
| `/performance` | Existing return/value/flow series, benchmark and attribution views; `historical-page`, `historical-chart` | G | historical-ui; historical-query; performance-navigation-flags | D |
| `/income` | Historical income and cash-flow selectors, exact tables and charts; `historical-page`, `historical-results` | G | historical-ui; historical-query | D |
| `/xray` | Saved effective exposures, unknown coverage and source links; `xray-page` | G | xray-ui; xray-query | D |
| `/xray/sources/[snapshotId]` | Retained constituent holdings, license and scoped/owner-wide source diagnostics; existing page composition | G | source-detail-account; xray-client | S |
| `/risk` | Versioned definitions, saved risk jobs, estimates and gaps; `risk-page`, `risk-results` | G | risk-query; risk-actions; risk-client | D |
| `/scenarios` | Existing versioned stress/shock assumptions, jobs and results; `scenario-page`, `scenario-forms`, `scenario-results` | G, scenario-workspace | scenario-forms; scenario-results | D |
| `/projections` | Existing projection/goal assumptions, lifecycle and saved modeled results; `projection-page`, projection editors/results | G, projection-workspace | projection-page; projection-query; projection-client | D |
| `/research` | Retained source, portfolio facts, owner-note/review forms and explicit report link; `research-page`, `research-forms`, `research-views` | G, research-workspace | research-forms; research-client; research-actions | D, A |
| `/aggregation` | Existing selected-account aggregation, saved FX choices and result coverage; `aggregation-page`, `aggregation-forms` | G, aggregation | aggregation-forms; aggregation-result; aggregation-fx-picker | D |
| `/reports` | Report/export selection, history, job status and manifest; report selection/history/status components | G, report-view | report-ui; report-query; report-download | D |
| `/reports/premium` | Existing risk/scenario/research/projection report profiles and private downloads; premium/research/projection report components | G, report-view | premium-report-profile-ui; research-report-selection; research-report-exports; projection-report-ui | D, A: research profile |
| `/alerts` | Rule editor, evaluation/lifecycle history and delivery state; alert editor/history/command components | G, alert-view | alert-ui; alert-query; alert-actions | D |
| `/settings` | Appearance, read-only configuration, provider status and PWA controls; `theme`, `pwa-settings`, `premium-provider-status` | G, pwa | theme; theme-layout; pwa-worker; premium-provider-client | D, F |
| `/settings/layouts` | Existing account-scoped saved workspace layouts; `owner-layout-page` and forms | G, owner-layouts | owner-layout-views; owner-layout-forms; owner-layout-query | D |
| `/sign-in` | Explicit Demo/local-session entry with saved appearance; `sign-in-panel` | G | theme-layout; account-selection; existing auth browser specification | F, A |

The six references guide Overview, Holdings, X-ray, Performance, Scenarios and
Alerts presentation. Existing canonical data remains authoritative: no overview
history curve, per-holding price history, extra scenario model or missing value was
invented to imitate a reference. Chart geometry remains separate from exact labels,
currency, timestamps, quality, provenance and table alternatives.

## Seven preserved HTTP bridges

These existing handlers remain separate from the 32 page routes. Shared handler
source and U support preservation; the last column states the new browser scope.

| Bridge | Preserved boundary | New browser evidence |
| --- | --- | --- |
| `POST /api/auth/demo-session` | Explicit Demo mode, same origin and protected session cookie | F: Demo entry on all three devices |
| `POST /api/auth/local-session` | Explicit local API mode, same origin and protected session/CSRF cookies | A: genuine local sign-in on all three devices |
| `POST /api/auth/sign-out` | Session revocation, protected-cookie expiry and fail-closed API revocation; visual preference remains independent | F: Demo sign-out and retained dark choice; no new authenticated API sign-out claim |
| `GET/POST /api/refresh` | Exact account/run parameters, authorization and private no-store status; POST requests only the allowed read-only refresh operation | Source plus `refresh-route`/`refresh-control` regressions; no new refresh-command browser execution |
| `POST /api/reports/[reportId]/artifacts/[artifactId]/download` | Shared `serveReportArtifact`: current authorization, account/profile/grant binding, expiry, private delivery and byte integrity | Source plus report-download regressions; no new ordinary-report download claim |
| `POST /api/exports/[exportId]/artifacts/[artifactId]/download` | Same typed shared boundary for the exact export artifact | Source plus report-download regressions; no new export download claim |
| `POST /api/premium-reports/[reportId]/artifacts/[artifactId]/download` | Same boundary, including current source permission recheck and profile selection | A: all twelve four-format downloads and revoked-download denial |

The public immutable PWA offline shell (`offline-v1.html`/`offline-v1.css`) retains
its intentional fixed-dark palette and versioned cache policy. It contains no
account data and does not follow authenticated workspace appearance. The service
worker's exclusion of authenticated HTML, RSC, API and report content remains.

All routes remain implemented; the five S-only deep paths are a new-browser
coverage limitation, not missing functionality. Full historical matrices and
multi-hour qualification were NOT RUN under this representative milestone. Earlier
failures, original thresholds, formal phase acceptance, deferred CI, P3-10 and
external/provider/production/distribution decisions retain their separate status.
