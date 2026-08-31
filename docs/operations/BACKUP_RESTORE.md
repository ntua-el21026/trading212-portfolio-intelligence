# PostgreSQL Backup and Restore

**Status:** Phase 1 operational contract

PostgreSQL is the authoritative system of record. Redis is intentionally omitted
from financial backup and recovery: queued work may be reconstructed from durable
runs/checkpoints, while canonical facts, snapshots, provenance, reconciliation,
and audit records must be recovered from PostgreSQL.

## 1. Production policy gates

Before production readiness, the owner must select and record RPO/RTO targets,
retention, backup region/account isolation, and key ownership. Automated backups
must be encrypted in transit and at rest, immutable for the selected retention
window, monitored, and periodically restored into an isolated environment.

A backup success notification is not restore evidence. Record the backup ID,
database version, completion time, checksum/provider integrity result, encryption
key reference, restore exercise, Alembic revision, and validating release SHA.
Never put a plaintext secret or credential bundle in this record.

## 2. Local logical backup exercise

The following creates a permission-restricted custom-format dump on the host.
Run it from the repository root after PostgreSQL is healthy:

```bash
set -euo pipefail
backup_directory=work/backups
backup_timestamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_file="${backup_directory}/portfolio-${backup_timestamp}.dump"
mkdir -p "${backup_directory}"
chmod 700 "${backup_directory}"
docker compose exec -T postgres pg_dump \
  --format=custom --compress=9 --no-owner --no-acl \
  --username=portfolio --dbname=portfolio > "${backup_file}"
chmod 600 "${backup_file}"
sha256sum "${backup_file}" > "${backup_file}.sha256"
printf 'Backup written to %s\n' "${backup_file}"
```

Keep `work/backups/` outside Git and do not upload a real portfolio dump to an
issue, pull request, chat, or CI artifact. For production, prefer the managed
PostgreSQL backup facility plus an independently tested logical/export strategy.

## 3. Isolated restore validation

Never test a restore over the active database. Choose a new, explicit validation
database name and verify it does not exist before proceeding:

```bash
set -euo pipefail
backup_file=work/backups/REPLACE_WITH_EXACT_BACKUP.dump
restore_database=portfolio_restore_validation
test -f "${backup_file}"
sha256sum --check "${backup_file}.sha256"
docker compose exec -T postgres psql \
  --username=portfolio --dbname=postgres \
  --set=ON_ERROR_STOP=1 \
  --command="SELECT 1 FROM pg_database WHERE datname = '${restore_database}'" \
  --tuples-only | grep -qv 1
docker compose exec -T postgres createdb \
  --username=portfolio --template=template0 "${restore_database}"
docker compose exec -T postgres pg_restore \
  --exit-on-error --no-owner --no-acl \
  --username=portfolio --dbname="${restore_database}" < "${backup_file}"
DATABASE_URL="postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/${restore_database}" \
  uv run alembic -c alembic.ini current
```

The preflight query deliberately fails the pipeline if the target already
exists. Use a different exact name rather than adding a destructive `--clean`
flag.

Validate, without exporting private rows:

- the expected Alembic head;
- owner/account relationships and authorization boundaries;
- source-record counts/fingerprints and ingestion checkpoints;
- immutable snapshot/component counts and source cutoffs;
- calculation method/version/provenance metadata;
- reconciliation runs/discrepancies and audit events;
- API/MCP cross-owner denial and deterministic fixture calculations;
- application behavior with broker egress disabled.

Only after retaining the evidence may the operator explicitly remove the exact
isolated validation database. Never generalize the name with a glob or variable
that has not been printed and reviewed.

## 4. Incident recovery

1. Contain ingress and broker egress; preserve logs/audit evidence.
2. Identify the last known-good backup and verify its integrity and encryption
   access without exposing key material.
3. Restore into an isolated database and complete the checks above.
4. Promote through the deployment platform's reviewed database procedure.
5. Run migrations only when their compatibility with the restored revision is
   established.
6. Reattach external secret references deliberately; rotate credentials after
   suspected compromise.
7. Resume workers gradually, reconcile against new Demo/read-only observations,
   and keep discrepancies visible.
8. Record actual data loss/time-to-recovery against the selected RPO/RTO.

Credential values are not canonical database fields, but opaque references and
private financial data are still sensitive backup content.
