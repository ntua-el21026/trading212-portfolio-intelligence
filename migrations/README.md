# Database migrations

PostgreSQL 18 is the authoritative Phase 1 data store. Apply migrations before
starting a newer API, worker, or MCP release:

```bash
make migrate
```

Migration files are immutable after release. Production rollbacks are
forward-fix migrations plus application rollback after compatibility review;
destructive Alembic downgrades are not an operational rollback mechanism. The
baseline downgrade exists only for empty disposable local/test databases and is
exercised by migration tests. Never downgrade a database containing portfolio
history without an independently verified backup and an approved data plan.

Generate a revision only after changing ORM metadata, then inspect the result:

```bash
uv run alembic -c alembic.ini revision --autogenerate -m "describe schema change"
uv run alembic -c alembic.ini check
make test-migrations
```

The runtime URL comes from `DATABASE_URL`; no production credentials belong in
`alembic.ini`.

The stabilization repair `20261113_0034` follows applied revision `20260915_0030`.
It corrects only native aggregation proof decoding for the existing exact
`$decimal` and UTC `$datetime` source tags; source records and financial results
are preserved. Revisions 0031–0033 remain reserved for the unintegrated historical
handoffs recorded in the Phase 3 resume document. Any future authorized handoff
integration must be authored against the actual current ledger, preserving those
historical handoffs instead of silently splicing them into the applied chain.
The repair permits downgrade only in a disposable database with no aggregate
selection or owner-erasure identity; populated operational rollback remains a
forward fix.
