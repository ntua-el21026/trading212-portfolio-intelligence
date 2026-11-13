# Trading 212 Portfolio Intelligence

A strictly read-only portfolio analytics platform combining brokerage ingestion,
financial accounting, reconciliation, saved analysis and API, web and MCP views.
Monetary values use explicit currencies and Decimal representations; source,
valuation time, coverage and quality remain attached to results.

## Current status

**Phase 3 is in progress.** The current authority is
[PROJECT_STATUS.md](PROJECT_STATUS.md) and the
[30 September checkpoint](docs/implementation/PHASE_3_RESUME_20260930.md).
Aggregation publication still fails a PostgreSQL native-component proof guard;
its runtime/browser acceptance and package-wide Phase 3 acceptance remain
pending. Historical component test receipts do not constitute a current release
pass. Production deployment and live-provider use are not authorized by them.

Phase 1 has source-bound acceptance evidence. Phase 2 was accepted by the owner
for progression after the R-01/R-02 corrections; that decision is distinct from
independent verification of every release gate.
[Machine status](PROJECT_STATUS.json) and
[progress](PROJECT_PROGRESS.json) retain current versus historical selectors.
Earlier README delivery records are preserved in the
[historical snapshot](docs/history/readme-before-portfolio-preparation.md).

## Architecture and implemented scope

~~~text
Next.js web / PWA ---- HTTPS API ----+
                                    +-- application services -- Decimal analytics
MCP tools/resources ----------------+           |
Worker and retained jobs -----------------------+-- PostgreSQL / source evidence
                                                     |
                                              GET-only provider adapters
~~~

Source implements typed ingestion, quantity/cash/value reconciliation, snapshots,
cash-flow-aware performance, manual contribution planning, internal virtual
targets, reference-source coverage, look-through exposure, saved reports and
alerts. Risk, scenario, projection and research components have scoped evidence;
their presence does not establish complete Phase 3 acceptance. PostgreSQL is
authoritative; Redis supports coordination and caching.

The broker boundary permits exactly the
[allowlisted capabilities](config/contracts/trading212-read-allowlist.yaml).
There is no broker order, transfer, CFD or Trading 212 Pie mutation. Internal
targets and manual allocation proposals do not execute broker actions. Browser
and MCP clients receive authorized projections rather than broker credentials
or generic HTTP, SQL or filesystem access.

## Local development

The workspace contains [API](apps/api/), [worker](apps/worker/),
[MCP](apps/mcp/) and [web](apps/web/) applications. Shared packages cover
[domain contracts](packages/domain/), [analytics](packages/analytics/),
[persistence](packages/persistence/), [security](packages/security/) and the
[sealed broker adapter](packages/trading212/). The tracked synthetic fixtures
and contract specifications support inspection without a brokerage account.

Use Python 3.13.15, Node.js 24.20.0, pnpm 10.34.5, uv and GNU Make. Docker Compose
is required for database-backed and full-stack gates. Review the
[dependency baseline](docs/implementation/P1_01_DEPENDENCY_BASELINE.md) and
[operations guide](docs/operations/LOCAL_AND_DEPLOYMENT.md) before starting
services. Keep secrets server-side in ignored local configuration. Use synthetic
seed data before configuring any external read-only provider.

~~~bash
make bootstrap
make docs-check
make format-check
make lint
make typecheck
make test-unit
make build
~~~

These are project commands, not a claim they all pass at this checkpoint.
make run-dependencies starts local dependencies; make run-local performs the
documented migration/seed/start sequence. Review account-selection configuration
and the current checkpoint instead of copying a historical scratch override.
No provider connection is needed for synthetic unit tests.

### Configuration without a broker connection

Use [.env.example](.env.example) as the configuration reference. Copy it to an
ignored `.env` for Compose and set a local database password; host processes
require explicitly exported settings. Keep these synthetic defaults for an
initial local review:

```dotenv
T212PI_ENVIRONMENT=local
T212PI_WORKER_PROVIDER=synthetic
T212PI_TRADING212_ENVIRONMENT=demo
T212PI_TRADING212_LIVE_ENABLED=false
T212PI_RUN_TRADING212_DEMO_SMOKE=0
T212PI_TRADING212_CREDENTIAL_BUNDLE=
```

Local synthetic authentication is restricted to loopback. Review the
[credential and Demo procedure](docs/operations/CREDENTIALS_AND_DEMO_VALIDATION.md)
before any separately authorized provider validation. Private credential files,
the original operator's environment and external checkpoint diagnostics are
absent from a clean clone; their absence does not prevent reviewing source or
synthetic test cases. The September resume document records those historical
local paths, rather than portable prerequisites.

## Verification and interpretation

Tests separate unit, property, contract, security, migration, integration and
browser checks. An offline pass does not qualify a database, browser, deployment,
licensed data source or real opening-history coverage.
[VALIDATION_REPORT.md](VALIDATION_REPORT.md) retains exact-source historical
observations; [PROJECT_STATUS.md](PROJECT_STATUS.md) identifies outstanding gates.
Do not combine repeated or differently scoped receipts into a new acceptance.

For a first technical review, read the
[design index](docs/DESIGN_INDEX.md),
[financial policy](docs/analytics/FINANCIAL_CALCULATION_POLICY.md),
[reconciliation policy](docs/analytics/DATA_QUALITY_AND_RECONCILIATION.md),
[security architecture](docs/security/SECURITY_ARCHITECTURE.md) and
[Trading 212 contract](docs/integrations/TRADING212_API_CONTRACT.md).

## Provenance and release

This independent project is maintained by Michail-Athanasios Peppas. Source,
dependency locks, synthetic fixtures and source-bound receipts provide evidence;
repository size and test inventories are not product acceptance. Retained
agent-assisted development/review records document assistance without replacing
technical validation.

The existing [proprietary license](LICENSE.md) remains in force. Review provider,
reference-data and third-party rights and use synthetic data for a public
demonstration. Accessibility, licensing and deployment are separate decisions.
The standing [delivery policy](AGENTS.md) is to commit directly to `main`, with
no branches or pull requests, using small, fast-forward commits. Historical
task-specific branch records describe earlier work. Git delivery, release
acceptance and production deployment are separate decisions.
