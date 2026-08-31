# Phase 1 Monitoring Contract

Dashboards and alerts use bounded-cardinality labels and sanitized metadata. No
portfolio payload, credential, account/owner/run identifier, instrument/ticker,
provider response body, request header, cookie, token, or raw URL becomes a
metric label or trace attribute.

## Required signals

- API/MCP request totals, duration, status class, active requests, and readiness;
- worker queue depth, lease/attempt/duration/outcome and interruption recovery;
- provider capability (fixed ten-value label), duration, sanitized error class,
  retry/rate-limit state, and freshness;
- ingestion page/record counts, checkpoint lag, partial/failure state;
- database pool/query/migration health;
- reconciliation discrepancy severity/count and dataset quality/freshness;
- authentication denials and redaction-canary health;
- backup completion/failure and last verified restore age.

Structured logs carry service/version, UTC time, event, status, duration/count,
correlation ID and ingestion run ID where useful. Those IDs belong in logs/traces,
not unbounded metric labels. Trace application/database/provider spans without
headers or payloads. Configure sampling, export, retention, access controls, and
the error-reporter adapter in the deployment platform.

Initial alerts cover service unready/restart loops, migration/database failure,
worker backlog/lease exhaustion, repeated provider authentication/schema/rate
failure, stale data, reconciliation escalation, backup/restore-test failure,
elevated authorization denial/error/latency, and storage exhaustion. An observed
broker write attempt is critical even if rejected upstream.

Every alert links to the sanitized procedures in
[`docs/operations/TROUBLESHOOTING.md`](../../docs/operations/TROUBLESHOOTING.md).
Verify signal delivery and redaction in staging before claiming deployment
readiness.
