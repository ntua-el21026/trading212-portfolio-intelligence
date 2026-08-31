# Infrastructure boundaries

- `docker/` owns build definitions for independently runnable Phase 1 processes.
- `deployment/` owns provider-neutral deployment examples and controlled migration jobs.
- `monitoring/` owns bounded-cardinality dashboards, alerts, and telemetry configuration.

The root `compose.yaml` is the local dependency stack. PostgreSQL is authoritative; Redis is optional and non-authoritative.
