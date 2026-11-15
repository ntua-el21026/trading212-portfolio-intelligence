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

## Current additive head

The current source head is `20261115_0036`, after `20261114_0035` research-report
provenance and `20261113_0034`. Revision `0035` adds four tables; `0036` adds no
tables, so the ORM inventory remains 368. The new revision changes only the two
`analytics_runs` canonical-byte checks to include X-ray in the existing 32-MiB
branch. Historical 32-MiB and ordinary 8-MiB kinds remain unchanged, as do public
response, report, artifact and scratch limits.

Upgrade validates the replacement checks transactionally. Downgrade takes the
same table lock and refuses if retained X-ray input or result exceeds the prior
8-MiB limit; it never truncates, deletes or rewrites immutable evidence. Populated
synthetic compatibility exercises retain verified backups before each transition.
Operational rollback remains a reviewed forward fix, not a destructive downgrade.
See the [current qualification record](../docs/implementation/PHASE_3_CHECKPOINT_B_CONSOLIDATED_20261115.md)
for actual sources, failures and focused results; no production migration is claimed.
