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
