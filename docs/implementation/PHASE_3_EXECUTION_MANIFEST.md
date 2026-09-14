# Phase 3 Execution Manifest

**Status:** Accepted implementation design; no package locally complete

**Baseline:** d2ebdaf96d1b61aacea5c6492824946540f88803

**Governance:** 30fe2ede666bff35e3e95173abcf34558a729cc1

Implement P3-01 through P3-10 as complete vertical capabilities. Shared infrastructure
may be delivered with its first real consumer. A dependency is implementation order,
not permission to leave downstream web/MCP/report behavior unfinished. Preserve main-only
linear delivery, frozen dependencies, historical regressions and one scoped Compose
project. Provider credentials are not required for synthetic contract/replay completion.

| ID | Identity | Primary user journey | Required scenario ownership |
| --- | --- | --- | --- |
| P3-01 | Advanced risk analytics | Select history/calendar/currency, create risk run, inspect metrics/matrix/coverage and source dates. | P3-S01, P3-S02, P3-S03, P3-S04, P3-S05, P3-S06, P3-S07, P3-S08, P3-S09 |
| P3-02 | Stress and scenario engine | Create a scenario version, run against a pinned portfolio, compare saved outcomes and historical replay. | P3-S10, P3-S11, P3-S12, P3-S13, P3-S14 |
| P3-03 | Monte Carlo and goal planning | Save assumptions and a goal, run a seeded projection, inspect nominal/real paths, shortfalls and sensitivity. | P3-S15, P3-S16, P3-S17, P3-S18, P3-S19, P3-S20, P3-S21, P3-S22 |
| P3-04 | Research cockpit | Review exposure-ranked events, cite facts, save thesis revisions and mark material changes reviewed. | P3-S23, P3-S24, P3-S25, P3-S26 |
| P3-05 | Rich ChatGPT UI | Use signed-JWT tools and canonical responsive widgets for existing and premium analyses. | P3-S33, P3-S34, P3-S36 |
| P3-06 | PWA and premium product polish | Install the app, use navigation/search/saved views, then verify safe offline/logout/account switching. | P3-S37, P3-S38, P3-S39, P3-S40 |
| P3-07 | Premium data providers | Inspect configured/blocked providers and compare explicitly selected licensed source coverage. | P3-S27, P3-S28, P3-S29 |
| P3-08 | Multi-account and multi-broker readiness | Select authorized accounts, reconcile FX/consolidation/transfers and compare the synthetic second broker. | P3-S30, P3-S31, P3-S32 |
| P3-09 | Security, performance, and resilience hardening | Inspect bounded jobs/alerts, exercise failure/recovery and restore a clean synthetic database. | P3-S41, P3-S42, P3-S44, P3-S46, P3-S47 |
| P3-10 | Release candidate and final acceptance | Install/upgrade the exact candidate, replay all journeys, inspect the portable evidence and external gates. | P3-S35, P3-S43, P3-S45, P3-S48 |

## Evidence sequence

Before a coherent direct-main commit, refresh remote main fast-forward only, inspect
all changes, run relevant formatting/lint/typing/contracts and focused behavior gates.
Use actual PostgreSQL/migration and browser/API-backed tests for persistence/UI changes.
Record focused and milestone failures without overwriting them. Final full validation
runs at one immutable implementation source, including security/image/restart/restore
checks outside make validate. Later documentation requires exact non-documentation
content/type/mode equivalence; executable governance is never documentation-only.

The 48-scenario ledger and 30 local acceptance rows are design inventories, not prior
Phase 2 counts or evidence. At the final boundary every predicate requires actual
inspectable originals in the portable pack. Local completion, independent review and
production readiness are separate. External account/licensing/public deployment gates
remain honestly blocked/unverified; GitHub Actions stays deferred_by_owner.
