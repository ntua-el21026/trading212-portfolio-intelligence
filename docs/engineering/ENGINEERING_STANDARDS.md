# Engineering Standards

**Status:** Accepted

## 1. General

- Optimize for correctness, explicitness, testability, reproducibility, and secure failure.
- Keep commits directly on `main` small, coherent, and passing required gates.
- Do not commit generated secrets, private data, local databases, caches, build output, or reports.
- Documentation and machine-readable progress change with behavior.
- Do not introduce abstraction without a real boundary, but preserve the provider/domain/interface boundaries in the design freeze.

## 2. Python

- Python 3.13 baseline.
- `uv` manages environments, workspace packages, and a committed lockfile.
- Full type annotations for production code; strict mypy configuration with narrowly documented exceptions.
- Ruff for formatting/linting/import rules.
- Pydantic v2 at external/API configuration boundaries; domain value objects remain framework-light.
- SQLAlchemy 2 typed declarative/core patterns and Alembic migrations.
- Async only at I/O/concurrency boundaries; pure calculations remain synchronous unless evidence requires otherwise.
- `Decimal` from validated strings/integers; never `Decimal(float)`.
- Timezone-aware UTC (`datetime` with explicit timezone); naive datetimes rejected.
- Exceptions use a stable domain/application taxonomy; no broad swallowing.
- Public functions/classes have concise contract docstrings where types do not express semantics.

## 3. TypeScript/web

- Node.js 24 LTS baseline and pnpm 10 workspace with committed lockfile.
- Strict TypeScript; avoid `any`, unsafe casts, and unchecked JSON.
- Next.js/React architecture follows server/client boundaries that keep secrets server-side.
- Generated API types/client from versioned OpenAPI where practical.
- Decimal-safe handling for authoritative financial values.
- Accessible semantic HTML first; custom widgets only with complete keyboard/ARIA behavior.
- State/data fetching separated from presentation; no duplicated financial arithmetic in components.
- Errors/loading/empty/stale/partial states are first-class.

## 4. Database and migrations

- PostgreSQL is authoritative.
- Every schema change has a migration.
- Applied migrations are immutable; corrections use new migrations.
- Migrations test upgrade from empty and previous supported state; destructive operations require documented backup/rollback plan.
- Constraints enforce identities, ownership, currency, idempotency, and required invariants.
- Queries are bounded/indexed; request paths do not perform accidental N+1 or full-history scans.
- Repository layer owns persistence mapping; interfaces do not expose ORM entities.

## 5. API/contracts

- Versioned `/api/v1` and stable MCP tool names.
- Authoritative decimals serialized as strings.
- Explicit nullability; missing is not zero.
- Cursor pagination and bounded limits.
- Stable error codes and correlation IDs.
- OpenAPI/schema changes tested for compatibility.
- No generic arbitrary query/path/filter language.

## 6. Security

- Least privilege and default deny.
- No Trading 212 writes, generic broker request, or credential exposure.
- Input validation at every boundary.
- Secrets through interfaces/environment/manager, never source.
- Central redaction and safe error mapping.
- Dependency/secret/static/container checks as relevant.
- Any suppression/ignore rule has owner, reason, scope, and expiry/review.

## 7. Observability

Structured events include timestamp, severity, service/version/environment, correlation/request/run IDs, event name, safe resource IDs, duration/count/status, and sanitized error category.

Metrics use bounded-cardinality labels. Traces omit private payloads/secrets. Health endpoints distinguish liveness/readiness and dependency state without leaking configuration.

## 8. Testing expectations

Each behavior change includes the highest-value applicable tests:

- unit;
- property-based;
- provider contract/mock transport;
- persistence/integration;
- API/MCP contract;
- browser end-to-end;
- architecture/security negative;
- migration;
- performance/regression.

Tests are deterministic; clocks/randomness/external I/O are controlled. Flaky tests are defects, not routinely retried into green.

## 9. Commit discipline

Conventional messages such as:

```text
chore: bootstrap monorepo and toolchains
feat(domain): add decimal money and currency value objects
feat(trading212): add GET-only positions adapter
feat(ingestion): persist idempotent transaction checkpoints
fix(accounting): preserve unknown fee coverage
 test(security): reject non-allowlisted broker paths
 docs: record Phase 1 work-package completion
```

Before each commit:

1. synchronize/re-read current `main`;
2. run relevant full required gates;
3. review diff for secrets/private data/generated noise;
4. update docs/progress;
5. commit without force-push.

## 10. Definition of done for a work package

- Requirements and acceptance tests implemented.
- Failure and degraded states implemented.
- Unit/contract/integration tests pass.
- Types/lint/format pass.
- Security/privacy implications covered.
- Migrations/contracts/docs updated.
- Observability added.
- No known blocker hidden.
- `PROJECT_PROGRESS.json` accurately updated.
