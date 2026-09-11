# P2-08 Analytical Web Experience

Implementation is in progress from P207 closure 7d3a5f5. P207 retains its
[separate local acceptance](evidence/phase-2-p2-07-03c3c5b.json). Generated
contracts and source are integrated; P208 acceptance, feature-level visual
review and final same-source evidence remain pending. GitHub Actions is deferred
by the owner. P209 and P210 remain required; Phase 3 is outside this assignment.

The [accepted web architecture](../architecture/PHASE_2_WEB_INFORMATION_ARCHITECTURE.md)
and [Phase 2 methods](../analytics/PHASE_2_METHODS.md) remain authoritative.

## Account selection and navigation

The shared shell and server reads use the same authorized account selection.
An explicit malformed, repeated, or unavailable account never falls back to a
different account. With no explicit selection, a configured authorized account
or the sole authorized account is selected; otherwise the user chooses.

Switching account removes owned snapshot, target, plan, report and cursor pins.
Validated date filters can survive the switch. Resource detail routes return
to their section when changing account. An old account subtree is masked while
a different account is selected. Form state is scoped to its mounted account
view; durable command failures preserve the current inputs. A newer navigation
intent invalidates the UI continuation of an earlier save, including while Next
retains the old page during loading. Saved commands remain durable and retryable;
their late callbacks cannot redirect the newer view. Link navigation uses Next's
onNavigate semantics, preserving modifier clicks, downloads and canceled navigation.
Account switches and browser history also invalidate old continuations.
Plan history, revision, reset and pagination links retain the selected account.

Private Pie templates remain available without a broker account. Their explicit
template scope is distinct from an invalid account. Owner-wide source and benchmark
configuration has its own scope; it cannot expose another account's data.

The header refresh control calls the fixed authenticated refresh route and reads
the returned run by account and identity. Missing configuration, partial success,
failure and active execution remain explicit. Starting a job is not reported as
completed synchronization.

## Eighteen product experiences

| Experience | Route and feature |
|---|---|
| Portfolio overview | / with canonical totals, direct holdings and source timestamps |
| Virtual Pies | /pies with search, filtering, private templates and paged collections |
| Target-version editor | /pies/[portfolioId] with hierarchy, mapping, validation, publication and immutable comparison |
| Actual versus target | /drift with pinned snapshot and target, optional full-portfolio company actuals |
| Drift explorer | /drift with ranking, hierarchy drill-down and exact signed, absolute and relative values |
| Contribution planner | /planner and /planner/[planId] with durable manual proposals, constraints and revisions |
| Performance center | /performance with period, return basis, value, rolling and calendar views |
| Benchmark comparison | /performance and /sources/benchmarks/[definitionId] with pinned versions |
| Attribution explorer | /performance attribution view with source, coverage and residual context |
| Dividend and cash-flow center | /income and /dividends with independent paging and currency-aware values |
| Portfolio X-ray | /xray with company/classification exposure and complete path evidence |
| ETF overlap explorer | /xray held funds, pairs and common entities from one retained run |
| Reports and exports | /reports with durable jobs, private downloads, expiry and selected sources |
| Alert rules | /alerts rules view with explicit version lifecycle |
| Alert history/feed | /alerts history with separate acknowledgment, resolution and delivery state |
| Data sources and coverage | /sources with provider configuration, licensing, snapshots and gaps |
| Reconciliation and quality | /quality with independent legacy and intelligence panels |
| Settings and provider state | /settings and /sources with actual authorized configuration |

Route smoke coverage is distinct from feature-level acceptance of this table.
Desktop, tablet and mobile browser processes run serially against one PostgreSQL
container, with a disposable database per spec and viewport. Native Tab and
Shift+Tab checks run within the feature workflows as well as the shared shell;
they observe naturally settled scrolling without moving focus or scrolling to
rescue an obscured control. On mobile the header scrolls with the document:
native focus scrolling had left the account selector underneath its sticky
overlay even with scroll padding and margins. This follows the responsive
un-fixing approach in [W3C technique C34](https://www.w3.org/WAI/WCAG21/Techniques/css/C34).
The bottom navigation remains available; desktop and tablet retain their header.
Document scrolling is immediate so rapid native Tab presses cannot leave focus
behind an unfinished scroll animation. Horizontal table scroll padding and bounded,
wrapping disclosures keep controls readable within narrow table regions. When
native keyboard focus reveals only part of a table control, the shell reveals
that control by scrolling its nearest table horizontally. If native caret focus
leaves part of a form control below the viewport or behind fixed navigation, the
shell scrolls just enough to expose the complete control. Focus and selection are
retained; controls already in view do not move. Browser tests send real Tab/Shift+Tab;
they do not programmatically focus or scroll to satisfy the assertions.

## Exact presentation

NumberValue preserves the server's original decimal string in its canonical
attribute, tooltip and assistive text. Currency comes from each metric. Missing
dividend quantity remains unavailable and never becomes zero.

Snapshot charts use UTC observation times, explicit zero-inclusive value axes,
gap separation and an accessible table containing the original values, states
and source details. Mixed currencies and values that cannot be represented by
finite plotting coordinates are not silently plotted as comparable values.
Screen coordinates are presentation only; financial calculations remain server-side.

## Intelligence quality

One bounded GET at /api/v1/accounts/{account_id}/intelligence-data-quality
adds generated source-client access. It supports valuation, actual_vs_target,
drift, performance, benchmark, income, attribution, cash_flow and xray.
It requires portfolio and analytics read authorization. Activity and target
requirements depend on the selected kind. Missing additional scope returns the
closed permission-required response without the protected metric payload.

The quality projection keeps intrinsic calculation quality separate from current
source freshness, license availability and physical retention. It returns a finite
metric inventory and paged source identities, not arbitrary analytical fields.
Results are private and not cacheable. Source collections preserve their selection
identity and expiry; current permissions and retention are checked again on read.

The /quality URL independently validates the reconciliation and intelligence
panels. A bad cursor or filter in one panel does not reset the other panel's valid
selection. Changing kind or page size starts a new source traversal.

Migration 20260911_0016 adds temporary selection identity bindings and the
intelligence source collection constraints. It follows 20260910_0015 and stores
identities rather than licensed payload copies.

## Company actuals and report sources

Existing actual-versus-target and drift reads accept an optional xray_run_id.
Without that selection, all legacy drift fields retain their original values and
unavailability reasons; the separate company field explains its unselected scope.
The selected run must match the account, portfolio snapshot and financial cutoff.
The server projects direct, indirect and effective company exposure over the
complete portfolio, retaining exact lower bounds, quality, omitted-preview counts
and calculation identity.

Company exposure is a non-additive full-portfolio view. It is not an entity-target
allocation, company target drift or an optimized post-contribution projection.
Shared listing/instrument identities must not duplicate company economics.

The optional company pin can accompany a report containing drift, or a targets export, or a plans export
with audit fields. Irrelevant combinations fail before dispatch. Report
consumer time remains separate from the pinned financial cutoff. Copies enforce
current display, storage and report/export permissions and the shortest applicable
retention. Requests without the optional pin retain their previous canonical bytes.
The four report formats share the same captured basis and company actual rows.
PDF presentation places optional company tables after the selected drift tables;
the legacy section inventory remains unchanged. Effective cell quality expands
its declared report context, while cell-specific confidence and bounds remain exact.

The company basis comparison normalizes only the four source-reference inventories
whose input codec specifies sorted order. It preserves duplicate membership and all
other reconciliation values, identities and metadata. This prevents UUID ordering
from rejecting an otherwise identical sealed basis without rewriting stored bytes.

## Verification in progress

Focused unit and contract checks, real PostgreSQL permissions/retention/parity
tests, all three browser viewports and native keyboard navigation are required.
The held-response navigation regression uses real saved server actions and real
Next responses; a failed race precondition is not proof of the hypothesized defect.
Final evidence must bind actual source, execution, reviewed images and runtime
outcomes. Earlier package screenshots and counts are not P208 acceptance.

The final working checks passed 534 web unit cases, current dependency/security
policies, all static/generated checks and all six runtime-image builds. A broad
coverage run exposed a test-only frozen operational clock in company reports:
the database publication fence expired against real time during slow rendering.
The corrected fixture shares an advancing operational clock between report
service and job store, without changing financial cutoffs, producer clocks,
license checks or expiry assertions. All 11 company-report/artifact cases passed
under coverage afterward. The failed broad receipt is preserved; the 88% working
coverage aggregate is not immutable acceptance. A fresh full gate at the committed
source and actual three-viewport image review remain required.
