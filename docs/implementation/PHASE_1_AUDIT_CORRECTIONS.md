# Phase 1 independent audit corrections

**Status:** Complete at corrected immutable SHA `99df47b6633791c3900a52f46f56d48be922a436`.
**Starting main SHA:** `c7b0b7090f60354f0f1f7a3dabdb0030b6f87038`
**Previous accepted evidence:** `e13916eca34d8e3be1ed130248d6c3d1ed7e3869`
**Scope:** Stage A only. Phase 2 and Phase 3 remain `not_started`.

The earlier evidence remains historical. Both corrections, their regression
suites, all Phase 1 local gates, all mandatory synthetic scenarios, and all three
workflows passed at the corrected SHA above. Stage B is authorized to begin;
this evidence commit contains no Phase 2 code.

## Starting inventory and baseline

- Local branch: `main`; remote branch: `origin/main`; no other branch exists.
- Source and migration head at the start: `20260901_0007`.
- MCP: nine tools; Trading 212: exactly ten GET capabilities.
- `python3 scripts/validate_repository.py`: passed, 62 required files.
- `uv sync --frozen --all-packages --all-groups`: passed.
- `uv run ruff check apps packages scripts tests`: passed.
- `uv run mypy apps packages scripts tests`: passed.
- `uv run pytest tests/unit tests/property tests/contract tests/security`: 338 passed.
- `make bootstrap`: passed after restoring exact Linux Node `24.20.0`, bundled
  Corepack, and pnpm `10.34.5` in a temporary tool directory. No system interpreter,
  global package, lockfile, or shell configuration was changed.
- `make lint-web typecheck-web`: passed; `corepack pnpm test:unit`: 22 passed.
- Starting-SHA workflows: Quality `33563692864`, Security `33563692838`,
  Documentation `33563692843`, all successful. Scheduled Security `34105437458`
  also passed on the same starting SHA. These are baseline evidence only.

## F-01: hard collection snapshot capacity

Every materialization calculates active owner capacity under the existing
PostgreSQL advisory transaction lock before opening/consuming its source iterator.
There is no first-owner exemption. Streaming consumes at most remaining member
capacity plus one identities. On overflow, a savepoint rolls back every newly
created snapshot and member, including already inserted batches, even when the
caller catches the exception. No cursor or purported exact total escapes failure.

Successful traversal retains exact totals, immutable membership, deterministic
ordering, scope/filter/sort/source-snapshot binding, signed continuation and expiry.
Expired snapshots no longer consume active capacity even if the bounded
`SKIP LOCKED` cleanup batch cannot remove every expired row immediately.

Regression evidence is in:

- `tests/unit/application/test_collection_capacity.py`;
- `tests/integration/test_collection_query_snapshots.py`;
- `tests/integration/test_api_mcp_postgres_parity.py::test_hard_collection_capacity_reaches_api_and_mcp_without_cursor_state`;
- the existing API/MCP sanitized-capacity error tests and stable-pagination suites.

The store tests exercise capacity three/exact three, overflow at the fourth member,
overflow after an inserted 1,000-row batch, one remaining member, simultaneous
first requests against both quotas, and expired/locked cleanup backlogs. The
existing 2,505-member and more-than-10,000-activity tests remain required.

## F-02: selected export metadata

Strict provider DTO validation precedes selection of `reportId`, `status`,
`timeFrom`, `timeTo`, documented boolean `dataIncluded` flags, and
`downloadAvailable`. Both new provider response fingerprints and retained source
fingerprints use selected metadata. URL rotation alone does not create a semantic
source revision. Unknown additive fields are discarded from export DTO diagnostics as well. No URL
is followed or export created.

Alembic revision `20260907_0008`, after `20260901_0007`, strips the two legacy
top-level download-link key spellings only from object payloads for
`historical_exports`. It is null/absent-key safe and idempotent, does not alter
unrelated capabilities/keys, and creates no migration-time URL copy. Historical
opaque source fingerprints remain unchanged; new ingestion uses minimized identity.
Privacy deletion cannot be undone by downgrade.

An existing legacy full-payload fingerprint can produce one new selected-format
revision on its first replay after migration. The legacy-transition integration
test proves that subsequent URL rotations create no further revision. Export
metadata does not generate economic activity.

The URL canary is built only in test memory. Provider, persistence, canonical
API/MCP, exception, and telemetry tests verify minimization. The additional
`python -m scripts.check_export_url_canary` gate scans generated contracts,
retained fixtures, web runtime bundles, and browser artifacts after generation.
Report/export workflows do not exist in Phase 1; no claim is made about future
Phase 2 output before its own canary and acceptance gates run.

## Additional acceptance-gate corrections

The runtime audit found Debian package-manager executables in all six images.
Their final stages now remove package-manager executables and helper installations
while retaining `/var/lib/dpkg/status` for vulnerability and license inventory.
`python -m scripts.check_runtime_package_managers` probes immutable built image
IDs with no network, a read-only filesystem, dropped capabilities, and
`no-new-privileges`. Local container builds and the security image matrix enforce
this check.

The artifact canary scanner also inspects stored and deflated ZIP members because
Playwright traces compress response content. It enforces archive, member, expanded
byte, and member-count bounds, checks chunk boundaries, and fails closed on
unsupported, encrypted, corrupt, nested, or oversized archives. Seventeen security
tests cover plain and compressed artifact scanning without committing signed URLs.

## Working-tree verification before the correction commit

These results establish local readiness for the correction commit; they are not
immutable-SHA acceptance evidence. The final repetition encountered a port conflict
with the earlier temporary Compose acceptance stack before API-backed Playwright.
That stack was stopped without deleting its volume; the browser and remaining
gates were rerun. A complete corrected-SHA run was still required at that point:

- `make bootstrap` and `make validate`: passed, including formatting, linting,
  strict typing, generated contracts, Python/web builds, dependency audits,
  migrations, all test layers, and all six container builds.
- Final `make test-coverage`: 371 isolated tests and 73 PostgreSQL/Redis-backed
  integration/migration tests passed; combined branch-aware coverage is 85%.
- Web unit tests: 22 passed. Synthetic Playwright: 32 passed. API-backed
  Playwright after the HTML canary assertions: six passed.
- Final format, lint, type, documentation, generated-contract, and negative
  security checks passed; the security suite now contains 33 tests.
- Gitleaks 8.30.1 scanned the full 65-commit starting history without leaks.
  Semgrep 1.175.0 strict offline scans found no violations. Trivy 0.74.0 filesystem,
  configuration, secret, and license scans and all six immutable runtime-image
  scans passed the workflow HIGH/CRITICAL policy with `--ignore-unfixed`.
- All six runtime images passed the package-manager absence check while retaining
  operating-system inventory. Generated contracts, fixtures, web runtime bundles,
  and browser artifact scans passed the URL-canary check.
- An isolated full Compose deployment applied migration `20260907_0008`, proved
  repeated seed/ingestion idempotency and authenticated API/MCP/web parity, then
  passed worker interruption/redelivery and all-service restart with retained
  PostgreSQL state. The original refresh run was recovered without duplicated
  economic rows or a changed canonical portfolio result.
- The runtime export-URL rotation produced one selected-metadata revision.
  Runtime canary checks passed across 31 database tables, rendered/API/MCP
  artifacts, five service logs, and 41,822 application filesystem files.
- Application services ran as UID 10001 with read-only filesystems, all
  capabilities dropped, and `no-new-privileges`; PostgreSQL and Redis ran as
  UID 999 with their required writable data directories.

Docker Desktop startup required backing up inspected stale zero-byte runtime
sockets and starting the installed application. No Docker daemon, replacement
system interpreter, or global Node/Python toolchain was installed. Final checks
use the pinned uv 0.12.7, Python 3.13.15, Node 24.20.0, and pnpm 10.34.5.

## Corrected immutable-SHA acceptance

The following commands ran against clean `99df47b6633791c3900a52f46f56d48be922a436`.
No implementation edits occurred during validation. `make bootstrap validate`
completed end to end with exit 0; the working tree was clean afterward.

| Gate | Observed result |
|---|---|
| `python3 scripts/validate_repository.py` | Passed; 62 required files and exactly ten GET capabilities |
| `make bootstrap` | Passed with frozen locks and exact runtimes |
| `make format-check lint typecheck` (through `validate`) | Passed, including strict mypy and generated TypeScript compilation |
| Unit/property/contract/security targets | 371 isolated Python tests, including 33 security tests; 22 web unit tests passed |
| PostgreSQL/Redis integration and migration targets | 73 tests passed, including prior-head/empty/repeated upgrades and ORM drift |
| `make test-coverage` (through `validate`) | Combined branch-aware coverage 85% |
| `make test-e2e` (through `validate`) | 32 synthetic and six API-backed Playwright tests passed, retries disabled |
| `make docs-check security-check` (through `validate`) | Documentation, Semgrep, source secrets, pip-audit and production pnpm audit passed |
| `make build container-build` (through `validate`) | Python/web distributions and all six hardened runtime images passed |
| `make generated-check` | No OpenAPI/TypeScript contract drift |
| Export artifact CLI with nine required paths | Contracts, fixtures, web bundles/traces and browser artifacts passed |
| Gitleaks 8.30.1 history to corrected SHA | Exit 0; no leaks; scanner processed 66 commits from 67 reachable commits |
| Trivy 0.74.0 immutable source archive | Filesystem/configuration/secret/license policy passed |
| Trivy 0.74.0 six immutable runtime IDs | Every image passed vulnerability/secret policy |
| Isolated Compose acceptance | Migration, seed/replay, URL rotation, authenticated parity, worker recovery and full restart passed |

Trivy scan conclusions use the committed policy: HIGH/CRITICAL and
`--ignore-unfixed` where configured. Source license scanning mirrors a clean CI
checkout; it does not claim complete installed-node-package license inventory.
Lower-severity and unfixed vulnerabilities are outside that pass claim.

### Exact-SHA GitHub Actions

- [Quality run 34121465069](https://github.com/ntua-el21026/trading212-portfolio-intelligence/actions/runs/34121465069): successful, attempt 2.
- [Security run 34121465107](https://github.com/ntua-el21026/trading212-portfolio-intelligence/actions/runs/34121465107): successful, attempt 1.
- [Documentation run 34121465071](https://github.com/ntua-el21026/trading212-portfolio-intelligence/actions/runs/34121465071): successful, attempt 1.

Quality attempt 1 failed only because its browser runner could not resolve
`github.com` during checkout. Retrying that failed job at the same SHA succeeded;
no source change or test suppression was needed.

### Runtime and scenario evidence

The [machine-readable runtime evidence](evidence/phase-1-audit-99df47b.json)
records image IDs, synthetic counts, source SHA, canary scan counts, and the
observed stop/restart states. All 14 Phase 1 scenario requirements retain their
existing executable test references in the scenario ledger and passed again.

For scenario 14b, run `b9cec93b-0c0a-4dda-bf36-2c8c3ebbcf12` had one confirmed
publication, queue depth one while its worker was stopped, and one consumer
attempt after recovery; idempotent replay returned the same run. For 14c, all
seven services were observed exited before restart. The same PostgreSQL volume,
all recorded counts, and canonical summary hash
`07f13e364c3a43f1c517f30823a485f027047c4d8044604ced039d6d80056104`
were preserved. API, MCP and authenticated rendered web agreed on
`248431.27 EUR`; all nine MCP tools remained registered.

The runtime canary was absent from 41,822 application files, five logs, 121 rows
across all 31 tables, API/MCP/rendered-web artifacts, and metrics. The export
rotation created one safe semantic revision without duplicate economic activity.
Application UIDs were 10001; PostgreSQL/Redis UIDs were 999. All six images lacked
package managers; application root filesystems were read-only with all
capabilities dropped and `no-new-privileges`.

## Remaining external boundary

The four existing external provider/deployment conditions remain unchanged. No
Demo/Live connectivity, production identity/deployment, public MCP registration,
real-provider opening-history bridge, or production backup restore is claimed.
