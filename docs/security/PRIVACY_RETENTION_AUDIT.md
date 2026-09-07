# Privacy, Retention, and Auditability

**Status:** Accepted baseline; production durations finalized at deployment

## 1. Data classification

| Class | Examples | Handling |
|---|---|---|
| Secret | Broker API secret, auth signing key, access token | Secret manager only; never logged/exported |
| Highly sensitive financial | Positions, balances, transactions, dividends, reports | Authenticated least-privilege access; encrypted transport/storage |
| Sensitive configuration | Account IDs, target portfolios, alerts, research notes | Authenticated access; audit changes |
| Operational metadata | Run IDs, timings, sanitized errors | Restricted telemetry with minimization |
| Public/reference | Instrument/exchange data subject to license | License-aware storage/export |

## 2. Minimization

Persist only data required for portfolio history, reconciliation, analytics, provenance, operations, or legal/security obligations. Avoid storing full raw provider payloads when a sanitized canonical record plus fingerprint/selected source representation is sufficient. The owning schema documents each sensitive field's purpose.

Historical Trading 212 exports retain only `reportId`, `status`, `timeFrom`,
`timeTo`, the documented boolean `dataIncluded` flags, and `downloadAvailable`.
The upstream DTO is validated first. Download links and their components,
URL-specific hashes, encrypted values, or reversible encodings are not retained.
New fingerprints derive from the selected non-downloadable representation, so
rotating a link without changing semantic metadata does not create a revision.
No export is created and no download URL is followed.

Migration `20260907_0008` removes legacy top-level `downloadLink` and
`download_link` keys only from `historical_exports` source payloads. It retains
unrelated fields and capabilities, creates no backup copy of the removed values,
and leaves historical opaque source identities unchanged. Rolling application
code back must not re-enable URL retention; removed URLs cannot be restored by
migration downgrade.

Because legacy full-payload fingerprints remain immutable, the first replay of
an old scrubbed record may create one selected-format source revision. Subsequent
URL-only rotations deduplicate against that safe revision. This format transition
does not create canonical economic activity from export metadata.

## 3. Retention categories

Configurable policy distinguishes:

- canonical financial history;
- raw/sanitized source records;
- ingestion/reconciliation/calculation metadata;
- application audit events;
- operational logs/traces/metrics;
- generated reports/exports;
- backups;
- research notes/source cache.

Defaults favor long-lived canonical history needed for the product and shorter retention for raw payloads, telemetry, temporary exports, and source caches. Exact production durations are an external decision recorded before deployment.

## 4. Deletion

The system shall eventually support owner/account deletion that:

1. revokes broker/auth credentials;
2. stops scheduled jobs;
3. deletes or cryptographically renders inaccessible application data according to policy;
4. deletes reports/objects and queued jobs;
5. records a minimal non-sensitive deletion audit event;
6. handles backups according to documented expiration/restore isolation;
7. validates completion and reports exceptions.

Phase 1 must design ownership/foreign keys so deletion is feasible and provide development reset commands; full user-facing deletion workflow may be production hardening.

## 5. Exports

- Private and access-controlled.
- Generated asynchronously when large.
- Contain generation time, owner/account scope, period, method/version, quality warnings, and sensitivity label.
- Stored with expiration/retention metadata.
- Download access uses authenticated authorization or short-lived signed access.
- No secret or internal credential/configuration fields.
- Provider/license restrictions enforced.

## 6. Auditability

Audit records identify:

- actor/principal or system job;
- action type;
- affected opaque resource IDs;
- timestamp and correlation ID;
- before/after hashes or safe field-level changes where appropriate;
- outcome and safe reason;
- application version.

Audit logs are not a duplicate store of portfolio payloads and never contain secrets.

## 7. Backups

- Encrypted and access-controlled.
- Restore procedure tested before production readiness.
- Restore into isolated environment with secrets disabled and outbound provider access blocked until authorized.
- Retention and deletion implications documented.
- Backup health monitored.

## 8. Development/test data

- Synthetic deterministic fixtures only in source control.
- Sanitized provider recordings require review and automated secret/private-field scan.
- Production database dumps are not used locally.
- Screenshots and visual-regression baselines contain synthetic portfolios.

## 9. Privacy acceptance

- Every persisted sensitive entity has owner/account scope.
- No secret fields in API/MCP schemas.
- Logs pass canary-redaction tests.
- Export authorization/expiration tested when introduced.
- Retention configuration has safe defaults.
- Documentation names external decisions rather than inventing compliance claims.
