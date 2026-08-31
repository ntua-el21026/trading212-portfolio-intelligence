# ADR-0003 — PostgreSQL as System of Record

**Status:** Accepted  
**Date:** 2026-08-31

## Context

The platform requires exact numeric types, transactional idempotent ingestion, historical relations, ownership constraints, migrations, auditability, and analytical queries.

## Decision

PostgreSQL is the authoritative application database. Redis may provide cache, lock, rate, or queue coordination but is never the financial ledger/system of record. Object storage may hold generated reports/large artifacts with metadata and authorization in PostgreSQL.

## Consequences

- Use exact `NUMERIC`, timezone-aware timestamps, relational constraints, transactions, indexes, and Alembic migrations.
- Test migrations from empty and previous supported schemas.
- Redis/cache loss must not lose canonical portfolio history.
- Backups and restore validation are production gates.
