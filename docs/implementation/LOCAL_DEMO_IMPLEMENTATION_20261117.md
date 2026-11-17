# LOCAL/DEMO stabilization and UI implementation — 17 November 2026

**Owner:** Michail Athanasios Peppas.
**Current disposition:** LOCAL/DEMO COMPLETE — ACCEPTED — ARCHITECTURE FROZEN — PROJECT CLOSED by the owner on 17 November 2026.
**Accepted delivery snapshot:** `cd2ff67be870983b4a321d49b8d33bdc68d8ed2d`.
**Original delivery disposition:** implementation complete; independent review pending at delivery.

The [acceptance addendum](LOCAL_DEMO_ACCEPTANCE_20261117.md) records the subsequent
owner decision and scoped independent review. Its owner-reported test executions
are separate from the original receipts below. The [architecture freeze](../DESIGN_FREEZE_LOCAL_DEMO_20261117.md)
is an additive record of the accepted implementation; no historical result is
reclassified by acceptance.
**Starting main:** `f19caa1153b0cf3acc41c47aba3a773b888741ff`.
**Implementation commit:** `e1e8da74846d9a248740bbf7560ea9b7183b32bc`.
**Broader UI qualification baseline:** `65d1d0db8bc9b8bb2682bc74b73cdcd4c5828ffc`.

This is the bounded [owner-authorized LOCAL/DEMO milestone](LOCAL_DEMO_SCOPE_20261117.md).
Checkpoint B remains INCOMPLETE. All 30 Phase 3 acceptance rows and 48 scenarios
remain pending, zero accepted. No complete current-SHA Phase 3 validation pass,
production readiness, CI success, real-provider verification or distribution right
is claimed. P3-10 has not started.

## Changes and source qualification

| Commit | Purpose |
| --- | --- |
| `91fcb6d165b38cba4ffa2f12535fdc138349603f` | Record revised UI sequencing and targeted LOCAL/DEMO completion contract; correct trailing whitespace in the earlier bounded report. |
| `0487425dd81e42f735dbe6376f8d7fa9fe9281b6` | Opt into real UTC for the acquired research-report rendering test's worker clock; preserve controlled financial clocks and add clock/fencing regressions. |
| `0d8fdaaaa5f338e6b38e099921e4b58ed3198cb7` | Shared design system, responsive shell and persistent light/dark/system appearance. |
| `65d1d0db8bc9b8bb2682bc74b73cdcd4c5828ffc` | Theme existing charts and preserve source-row allocation color correspondence, with an independent synthetic regression. |
| `e1e8da74846d9a248740bbf7560ea9b7183b32bc` | Preserve the appearance selector's accessible name when compact CSS hides visual label text; add a regression. |

The final functional observations executed before these UI commits, at parent
`0487425...` with complete working-source manifest
`15c0bee3663ac15a87212809b8c4e0141d19e8b6074c70145951a8b7d3aa2172`.
The private `implementation-byte-equivalence.json` verifies **1,709 application,
package, test, migration and configuration paths** against the broader UI
baseline `65d1d0d`, with zero mismatches. These remain actual pre-commit executions,
not newly executed same-SHA or aggregate Phase 3 passes. Earlier observations keep
their distinct manifests; see the [78-item evidence overlay](LOCAL_DEMO_TRACEABILITY_20261117.md).
Documentation delivery and final live/local synchronization are recorded in the
private post-commit handoff, avoiding a self-referential commit claim here.

The final `e1e8da7` supplement changes one production `aria-label` attribute and
adds one regression; no other application, test, migration or configuration file
differs from `65d1d0d`. `compact-appearance-byte-equivalence.json` verifies 1,709
paths against that supplement's actual browser manifest `41f7f0ab...`, with zero
mismatches. Fourteen affected theme tests and twelve combinations of viewport and
appearance pass; earlier larger browser/report observations retain their original
source. They are not relabeled as a newly executed full final-SHA matrix.

## Application stabilization

A new PostgreSQL regression demonstrates the clock mechanism: an injected frozen
worker clock can consider a claim live after PostgreSQL's transaction timestamp
has passed its lease. The database rejects publication, and a real-time worker
reclaims with a new fence while the old claim remains invalid. The positive
acquired-FX rendering case now explicitly uses live UTC for worker operations.
Source-cutoff and financial fixture clocks, default controlled-time tests,
lease lengths, heartbeat intervals and every published migration remain unchanged.

Nine focused PostgreSQL cases, including the previously failing acquired-FX
four-format case, and two clock-selection unit cases pass. The original historical
`storage_unavailable` failure was not correlated to its exact database exception;
the demonstrated mechanism and focused recovery do not retroactively establish
that original cause or turn the failed complete suite into a pass.

The earlier SAST parser and pending-navigation Back fixes remain intact. There was
no new admission investigation, speculative production optimization, GC alteration,
CPU-quota change, broker request or lease correction in this package.

## Whole-application visual implementation

The six original mockups were located, ZIP-validated, hashed and individually
inspected. They guide visual hierarchy rather than financial data or unsupported
operations. The implementation covers all **32 page-route patterns**, 22 primary
destinations plus Settings, nested details and seven HTTP bridges. The complete
[route/feature checklist](LOCAL_DEMO_ROUTE_COVERAGE_20261117.md) distinguishes
browser-exercised routes from source/shared-regression coverage.

One semantic palette supplies global CSS, shared UI primitives and feature CSS
Modules. It covers navigation, forms, financial tables, notices, dialogs,
loading/empty/error states, chart axes/grid/series/tooltips and responsive surfaces.
Existing Recharts and Lucide components remain; the wordmark is first-party SVG.
There are no new dependencies, remote fonts, screenshot backgrounds or copied
mockup numbers. No historical overview curve, holding sparkline or projection
control was invented; Scenarios and Projections retain their separate semantics.

The responsive sidebar scrolls above its footer. A demonstrated selector conflict
and intrinsic mobile grid constraint were corrected without hiding controls or
masking overflow. Tablet wordmark sizing was corrected after screenshot review.
Native navigation, account masking, cursor/filter semantics and focus reveal remain.

### Appearance and accessibility

The validated, nonsensitive `pi_theme_v1` cookie stores `light`, `dark` or `system`.
The server emits the root preference and matching viewport color; CSS resolves
system mode before JavaScript and tracks OS changes. A narrow client provider
updates the enum, browser chrome and the header/Settings controls. It creates no
preference endpoint or table, adds no inline initialization script and changes no
CSP. Cookie reads make the root request-dependent; portfolio pages already require
request-scoped authentication. Blocked cookie persistence still allows the current
document to change appearance.

Tests cover persistence through reload, navigation, sign-out and actual account
switching; no-JavaScript checks cover initial light/dark/system rendering.
Opaque palette review passes 72 required text/control/focus/button contrast pairs.
Disabled-control colors are separately classified. Browser smoke checks cover skip
links, named tables, responsive controls, 320-pixel layout and a 200% **CSS
magnification stress probe** at 720 pixels. Native browser zoom and a comprehensive
accessibility audit were not executed; these observations are not an AA certificate.

**Deliberate PWA exception:** the immutable, public, no-JavaScript offline-v1 shell
and its fixed-dark manifest colors remain unchanged. They do not follow the saved
appearance cookie. Active application PWA/offline notices use the new palette.
Changing the separate fallback needs versioned asset/cache compatibility review;
this package does not relax its CSP or private-cache restrictions.

Four small first-party synthetic documentation captures are published with their
[hashes and source provenance](../media/local-demo-captures-20261117.json).
Before captures and the complete 38-image final matrix remain private.

## Actual targeted validation

Commands below ran through the private receipt operator, which retains exact
arguments, source manifests, exits, durations and output checksums. Node is
24.20.0, pnpm 10.34.5, application Python 3.13.15, Next.js 16.4.1 and Playwright
1.62.1. Existing dependencies and environments were reused. Heavy database,
browser and scanner operations were serial; no performance cohort was executed.

| Gate / command | Actual result | Receipt / limitation |
| --- | --- | --- |
| `pnpm --filter @trading212/web test:unit` | PASS: 980 tests / 112 files, exit 0, 8.965 s | `frontend-units`: earlier working manifest `ce18e6c...`; not relabeled as final-source complete units. |
| `pnpm --filter @trading212/web exec vitest run` with the nine affected theme/navigation/account/allocation/snapshot/historical/overview/currency files | PASS: 54 tests / 9 files, exit 0, 2.047 s | `final-affected-web-units`: final code manifest `15c0bee...`. |
| Focused `pytest` fixture-clock unit file | PASS: 2 cases, exit 0, 3.342 s | `report-clock-unit`: Python source-equivalent; unrelated frontend files changed during the execution. |
| Focused `pytest` clock-publication, acquired four-format completion, stale-claim reclaim and current-source authorization cases | PASS: 9 parameterized cases, exit 0, 181.517 s | `report-clock-postgres`: relevant Python source unchanged at delivery; not an immutable whole-tree invocation. |
| `pytest` allowlist, snapshot currency weights and three architecture/default-deny negative cases | PASS: 17 cases, exit 0, 4.453 s | `broker-security-financial`; relevant Python source unchanged. The separate inherited secret-check failure is not omitted from original suite reporting. |
| `pnpm --filter @trading212/web build` | Four initial exits 1, four unchanged normal retries exit 0 | `frontend-build*`, `frontend-reflow-build*`, `frontend-tablet-build*`, `compact-theme-build*`; original failures retained. Last successful build uses the accessibility supplement bytes. See dependency warning below. |
| `pnpm --filter @trading212/web typecheck` | PASS, final affected source exit 0, 0.888 s | `final-frontend-types`; build also completes its TypeScript stage. |
| `pnpm --filter @trading212/web lint` | PASS, final affected source exit 0, 7.421 s | `final-frontend-lint`. |
| `ruff check` and `ruff format --check` for the four changed Python files | PASS, exits 0 | `report-clock-lint`, `report-clock-format`. |
| `python scripts/generate_api_contract.py --check` | PASS, exit 0, 14.598 s | `generated-contract`; no schema or generated-client change. |
| Seven configured Semgrep rules over 16 changed Python/TypeScript targets | PASS, exit 0, 118.718 s; zero findings, parsed lines approximately 100% | `focused-sast`; not a new complete repository scan. No rules or exclusions changed. |
| Synthetic Demo browser protocol | PASS, exit 0, 15.779 s: 150 views, 38 captures, zero page/console errors | `demo-final-functional-recovery`: 25 paths × 2 themes × 3 devices, plus sign-in/detail/form/history/theme checks. |
| Direct authenticated research-report browser protocol | PASS, exit 0, 119.069 s | `local-api-research-ui-fresh-v2`: all 3 viewports, 12 genuine downloads, exact source values and independent PDF/CSV/XLSX/JSON inspection. |
| Direct-helper privacy canaries | PASS after explicit quiet-environment prerequisite, exits 0 | `browser-privacy-canary-quiet-02`, `browser-privacy-canary-v2`; original prerequisite exit 1 retained. Qualification applies to this direct helper, not every historical Playwright runner. |
| Compact theme accessibility regression and SSR/client theme tests | PASS: 14 cases / 2 files, exit 0, 1.869 s | `compact-theme-unit-recovery`; original red case is retained (5 pass / 1 fail). |
| Compact selector name, persistence and overflow across 320/390/768/1440 pixels × light/dark/system | PASS: 12 combinations, exit 0, 2.773 s | `compact-theme-browser-recovery`; original 320-pixel missing-name failure retained. |
| Focused lint after the accessibility correction | PASS, exit 0, 1.705 s | `compact-theme-lint`; final build also completes strict TypeScript. |
| Documentation, workspace, changed-file formatting and diff checks | Delivery checks recorded in private command index | Final statuses accompany the post-commit handoff; original failures remain separately indexed. |

The exact focused PostgreSQL invocation selected:

```bash
.venv/bin/python -B -m pytest \
  tests/integration/test_report_worker_clock_postgres.py \
  tests/integration/test_acquired_research_reports_postgres.py::test_acquired_fx_complete_chain_preserves_authority_and_four_format_proof \
  tests/integration/test_report_postgres.py::test_worker_reclaim_increments_fence_and_old_claim_cannot_publish \
  tests/integration/test_report_postgres.py::test_current_source_permission_denies_before_payload_read \
  -q --tb=short
```

The nine final affected Web files are `theme.test.tsx`, `theme-layout.test.tsx`,
`navigation.test.tsx`, `account-context.test.tsx`,
`allocation-color-correspondence.test.tsx`, `snapshot-chart.test.tsx`,
`historical-ui.test.tsx`, `overview.test.tsx` and `financial-currency.test.tsx` under
`apps/web/tests`. Browser helpers and their frozen hashes are retained privately
for independent reproduction; they launch no Playwright TestRunner or automatic
artifacts. Authenticated logs contain closed endpoint/status/check enums rather
than raw errors, HTML, cookies, headers or signed URLs. Intended synthetic report
files are retained in private storage.

## Failures, recoveries and unexecuted gates

- A final 320-pixel check found the appearance selector lost its accessible name
  when compact CSS hid label text. Both a real browser case and the new unit
  regression fail before the one-attribute correction. Fourteen affected unit
  cases and twelve viewport/theme combinations then pass; no larger unchanged
  suite was repeated for this attribute-only correction.
- The first new theme unit run failed because jsdom had no `matchMedia`. The
  controlled browser-API double was added; the original failure and recovery remain.
- A baseline visual attempt failed under production-mode configuration without
  the explicit local test environment. The unchanged pre-redesign build then
  captured seven before images; its frontend bytes match the starting SHA.
- The first CSS-magnification probe exposed real header/grid overflow. The source
  correction precedes the passing geometry and complete three-device smoke.
- A later functional helper retained the desktop viewport at its magnified test
  size before selecting desktop navigation. Restoring the declared viewport and
  honoring the existing empty-filter URL semantics corrected the helper; the
  failed execution remains. No product timeout, assertion or fixture was weakened.
- The first authenticated helper stopped with an item-read 503 after its ten-minute
  synthetic source lifetime elapsed during setup. Authentication and fixture
  metadata passed; no report was admitted. Source expiry is a supported explanation,
  not an independently correlated exception diagnosis. A backed-up fresh fixture,
  legal cursor-aware note inspection and the same production submission flow pass.
- The database preservation helper initially retained a stale runtime-receipt
  digest when selecting the second fixture; it stopped before data access. Its
  attempted dependent backup also failed without a dump. Correctly pinning the
  reviewed second runtime receipt preserved the original guards and produced a
  verified backup. Both operator failures remain in evidence.

**NOT RUN in this package:** complete `make validate`, complete 6,000-case Python
qualification, complete integration/coverage regeneration, historical browser/CWV
matrix, new admission experiments, new whole-tree paired Web builds, clean-install,
container rebuild/release qualification and nine-service restart/full restore.
Their original historical PASS/FAIL/PENDING_LOCAL results retain their source.
The owner explicitly made this reduced qualification scope applicable to Demo only.

The original admission requirement remains **FAIL**, not waived for Checkpoint B.
The retained last bare control reports admission p95 0.774257422 s against 0.750 s,
read p95 0.318458853 s against 0.500 s and maximum 12 read SQL statements, with ten
completed jobs and 30 reads. The separate covered execution's 4.034860579 s is not
a qualifying bare measurement. Whole-Web-tree byte equality remains historically
FAIL with 277 differences. Neither gate was rerun or relabeled.

## Security, rights and external gates

Production financial, broker, authorization, API/MCP, migration and dependency
sources remain unchanged; the exact ten-GET default-deny boundary and financial
currency/quality regressions pass their focused checks. No real broker/provider
request, account data, credentials, Live operation or generic HTTP capability was
introduced. Generated contracts and published migrations remain unchanged.

The pinned framework's build reminder returned `SecurityFatalError` after successful
compilation. Its own documented, unmodified normal retry returned 0; no skip flag,
security preference, package pin, scanner rule or branch was changed. The
[moderate Next.js cache advisory](https://github.com/vercel/next.js/security/advisories/GHSA-rhh4-g77r-r9qj)
remains a dependency limitation, with a patch recommendation. The source declares
neither `use cache` nor `cacheComponents`; this is not proof of comprehensive
runtime immunity. A separately reviewed dependency update is recommended.

At the prior f19 delivery, Gitleaks source/history exits were 1 (56 and 2 findings
respectively); the high-confidence checker exited 1 with 14 reviewed nonsecret
occurrences. Classifications do not turn those scans green. New complete
scans were not automatically repeated. A changed-source check is separately scoped
in the delivery index. At implementation delivery, security policies and LICENSE.md
were unchanged; the later approved wording correction is recorded below.

[Reproducibility and scanner proposals](../verification/LOCAL_DEMO_CONTRACT_PROPOSALS_20261117.md)
require owner review before changing any accepted contract. Public source visibility
is distinct from rights to redistribute dependencies, binaries or container images.
The owner subsequently approved and implemented the minimal [license-visibility
wording correction](../verification/LICENSE-VISIBILITY-WORDING-PROPOSAL.md) at final
LOCAL/DEMO closure. No distribution or licensing grant was made. CI remains owner-deferred and unverified; workflows
are not activated. Provider credentials, paid services, hosted OAuth/MCP registration,
production ownership, attestations and deployment remain separately gated.

## Resources and evidence delivery

The two unknown Redis keys were inspected through bounded metadata only: both are
stable one-member sets without expiry and do not match the exact pinned default
producer identities. Names and values were neither printed nor retained. They
remain **UNCLASSIFIED_METADATA_PRESERVE**. No deletion, flush, restart or weakening
of the existing preservation guard was attempted.

Two positively bound disposable API databases were dumped before their own fixture
shutdown: **3,565,125** and **4,817,775** bytes. Both `pg_dump` and catalog-list
verification exit 0; checksums and all 4,669 archive catalog entries are retained.
This is preservation evidence, not an executed restore or production RTO guarantee.
After fixture shutdown the four original database names remain, PostgreSQL and
Redis retain their original container identities and all sixteen Redis database
counts are unchanged. Task HTTP processes are stopped. The duplicate baseline
runtime clone was removed only after 1,781 ordinary files matched the preserved
original; no unique evidence was removed.

Original host build outputs are preserved in the new private preservation directory;
the current UI build remains available in the workspace. Previous archives,
qualified images, user volumes, .venv, dependency stores, Downloads references and
unrelated repositories remain preserved. No global pruning or broad cleanup ran.

The private delivery includes `COMMANDS.json`, a complete checksummed file manifest,
source and byte-equivalence records, failures/recoveries, 38 final visual captures,
before captures, three four-format report sets, both database backups and explicit
archive exclusions for preserved runtime/reference duplicates. Archive size,
SHA-256, inventory verification and final Git synchronization are recorded in the
post-commit private delivery record and conversation.

## Historical delivery review checklist

The subsequent [owner acceptance](LOCAL_DEMO_ACCEPTANCE_20261117.md) completed the
scoped independent LOCAL/DEMO review. The original handoff checklist below is
retained as historical context. Proposed policy changes, broader Phase 3 acceptance
and external deployment/distribution decisions remain separate.

- Review the LOCAL/DEMO scope, 32-route checklist, evidence qualifications, theme
  behavior, synthetic captures and known fixed-dark offline fallback.
- Review the exact 30-row/48-scenario overlay; keep every formal item pending until
  independent acceptance. Local Demo completion does not accept Checkpoint B.
- Decide separately on dependency patching, proposed reproducibility/scanner
  contracts, license visibility, distribution rights and any later qualification.
- Authorize P3-10, CI, providers, hosted integrations or production only through
  their separate gates. None is authorized by this delivery.
