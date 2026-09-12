# PostgreSQL Backup and Restore

**Status:** Phase 1 operational contract

PostgreSQL is the authoritative system of record. Redis is intentionally omitted
from financial backup and recovery: queued work may be reconstructed from durable
runs/checkpoints, while canonical facts, snapshots, provenance, reconciliation,
and audit records must be recovered from PostgreSQL. For Phase 2 this also includes
target/benchmark versions, licensed source records and current restrictions,
canonical analytics inputs/results, durable plan/report/alert jobs and outboxes,
private artifact bytes/manifests/grants, notification state and purge progress.
Do not infer recovery from Redis contents or Celery's result backend.

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
It is a local logical exercise, not an encrypted production backup or evidence of
a successful restore. Use the intended existing Compose project and its inspected
PostgreSQL volume; the examples use the repository's synthetic local database/user.
For customized credentials, use the existing private database authentication
configuration rather than putting secrets in command arguments or shared output.
Run from the actual WSL repository root after PostgreSQL is healthy. For a
controlled recovery exercise, quiesce application writes and job producers before
recording comparison counts/hashes, so their reference point matches the dump.

```bash
set -euo pipefail
umask 077
set -o noclobber
backup_directory=work/backups
backup_timestamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_file="${backup_directory}/portfolio-${backup_timestamp}.dump"
backup_partial="${backup_file}.partial"
mkdir -p "${backup_directory}"
chmod 700 "${backup_directory}"
test ! -e "${backup_file}"
test ! -e "${backup_file}.sha256"
docker compose exec -T postgres pg_dump \
  --format=custom --compress=9 --no-owner --no-acl \
  --username=portfolio --dbname=portfolio > "${backup_partial}"
mv --no-clobber -- "${backup_partial}" "${backup_file}"
test ! -e "${backup_partial}"
sha256sum "${backup_file}" > "${backup_file}.sha256"
printf 'Logical dump written to %s; restore validation is still required.\n' "${backup_file}"
```

The restrictive umask applies before opening the dump and checksum files. A failed
dump remains explicitly `.partial` and has no success checksum; preserve its safe
failure category, then remove only that exact disposable partial file when no
writer remains. Never rename a partial dump to manufacture a backup result.

Keep `work/backups/` outside Git and do not upload a real portfolio dump to an
issue, pull request, chat, or CI artifact. For production, prefer the managed
PostgreSQL backup facility plus an independently tested logical/export strategy.

## 3. Isolated restore validation

Never test a restore over the active database. Use only a trusted dump from the
recorded backup source. Keep API, MCP, web, dispatchers and workers disconnected
from the restore target; broker and external notification egress remain disabled.
Do not run the synthetic seed into restored data. Choose a new explicit validation
database name; the guard accepts only a short `portfolio_restore_` name:

```bash
set -euo pipefail
backup_file=work/backups/REPLACE_WITH_EXACT_BACKUP.dump
restore_database=portfolio_restore_validation
[[ "${restore_database}" =~ ^portfolio_restore_[a-z0-9_]+$ ]]
(( ${#restore_database} <= 63 ))
test -f "${backup_file}"
sha256sum --check "${backup_file}.sha256"
restore_exists="$(
  docker compose exec -T postgres psql \
    --no-psqlrc --tuples-only --no-align --set=ON_ERROR_STOP=1 \
    --username=portfolio --dbname=postgres \
    --command="SELECT count(*) FROM pg_database WHERE datname = '${restore_database}'"
)"
test "${restore_exists}" = 0
docker compose exec -T postgres createdb \
  --username=portfolio --template=template0 "${restore_database}"
docker compose exec -T postgres pg_restore \
  --exit-on-error --no-owner --no-acl \
  --username=portfolio --dbname="${restore_database}" < "${backup_file}"
DATABASE_URL="postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/${restore_database}" \
  uv run alembic -c alembic.ini current
```

The preflight accepts exactly a zero count. It does not infer absence from
`grep` over formatted/blank output; SQL failures stop execution, and `createdb`
also refuses an existing target. Use a different exact name rather than a
destructive `--clean` flag. A failed restore leaves an isolated incomplete
database for diagnosis; do not point services at it or mark it validated.

The Alembic command above reads the restored revision; it does not upgrade it.
Compare with the recorded backup revision and the intended image before any
migration. The host connection example uses the default local port; use the
inspected private connection configuration if this Compose project differs.

Validate, without exporting private rows:

- the expected Alembic head;
- owner/account relationships and authorization boundaries;
- source-record counts/fingerprints and ingestion checkpoints;
- immutable snapshot/component counts and source cutoffs;
- calculation method/version/provenance metadata;
- reconciliation runs/discrepancies and audit events;
- API/MCP cross-owner denial and deterministic fixture calculations;
- application behavior with broker and external notification egress disabled.

For Phase 2, extend the same isolated validation instead of treating the Phase 1
row inventory as sufficient:

- Compare target/benchmark version history, ownership and normalized parent links;
  confirm current selection, source/license versions, actual first-knowledge times
  and permitted immutable input/result digests against the backup reference.
- Compare plan/report/export job, request, input and finalized-result identities;
  inspect publication/consumer attempt counts, fences and lease times. Preserve
  queued/running/terminal distinctions. A restored transport message is not
  evidence of completion; allow bounded recovery only after the checks below.
- Check report manifests and artifact size/digest against stored permitted bytes
  without exporting those bytes. Validate owner/account/grant/current-license and
  expiry denials. Check source/report/alert purge markers, copied payloads and
  pending work, not merely surviving parent counts.
- Preserve alert rule versions/lifecycle, captured evaluation windows, economic
  deduplication/cooldown keys, event state and notification delivery identity.
  Replaying a delivery may be externally ambiguous; do not resend it to a real
  recipient as a restore test or claim exactly-once recipient acceptance.
- Verify collection owner/account/source binding and original expiry. Restore
  authorized signing-key references through the secret platform if continuity is
  required; do not copy key values into database rows or extend expired cursors.
- Reconcile post-backup credential/grant/license revocations and privacy-deletion
  decisions with their authoritative incident/configuration records **before any
  restored read or job is enabled**. A backup can contain bytes or grants revoked
  after it was taken; database restoration must not resurrect authorization.
  Keep the restore quarantined if current restrictions cannot be established.
- Use the actual current clock when checking expiry. Complete the approved bounded
  source/report/alert cleanup and inspect remaining purge work before exposure.
  The dispatcher schedules exact-source expiry on the existing dispatcher,
  as described in [Phase 2 operations](PHASE_2_OPERATIONS.md#retention-migration-and-backup).
  Verify that the selected release actually contains and has validated that
  composition; starting the dispatcher does not prove all pending work completed.

Only after retaining the evidence may the operator explicitly remove the exact
isolated validation database. Never generalize the name with a glob or variable
that has not been printed and reviewed.

## 4. Incident recovery

1. Contain ingress and broker egress; preserve logs/audit evidence.
2. Identify the last known-good backup and verify its integrity and encryption
   access without exposing key material.
3. Restore into an isolated database and complete the ownership/integrity and
   current revocation/deletion/expiry checks above. Preserve the prior database
   and its evidence; do not overwrite it to make the comparison agree.
4. Establish application/schema compatibility and perform only the reviewed
   migration plan against the isolated target. Serialize deployment migrations;
   Alembic's transaction is not a deployment lock or a data-restoration rollback.
5. Promote only through the deployment platform's reviewed database procedure.
   Reattach external secret references deliberately; rotate after suspected
   compromise. Keep notification delivery and provider egress disabled until their
   configuration and current grants have been separately reviewed.
6. Resume authorized reads, then job producers/consumers gradually. Inspect the
   actual fenced job/outbox/result transitions and pending cleanup; do not reset
   counters, rewrite captured inputs or infer completion from transport receipts.
7. Reconcile against new authorized Demo/read-only observations only when external
   configuration and permission are available; keep discrepancies visible.
8. Record actual data loss/time-to-recovery against the selected RPO/RTO, including
   unresolved restrictions and any intentionally unresumed external deliveries.

Credential values are not canonical database fields, but opaque references and
private financial data are still sensitive backup content.
