# ADR-0015: Versioned Alert Evaluation

**Status:** Accepted

**Date:** 2026-09-07

**Decision authority:** Current owner's Phase 2 design-closure assignment

## Context

Portfolio monitoring must explain which target, valuation, source cutoff,
quality state, and rule produced an event. Retries, worker restarts, corrected
data, acknowledgment, cooldown, and manual resolution must not produce hidden
duplicates or erase history. External email/webhook credentials are optional;
their absence cannot disable local evaluation or the in-app feed. Notification
delivery is an application side effect and never a broker action.

## Decision

Adopt `alert_evaluation_v1` version `1.0.0` and
[Phase 2 methods, section 8](../analytics/PHASE_2_METHODS.md#8-versioned-alerts-and-deterministic-evaluation).
Rules use bounded typed family/metric schemas for target/group/holding drift,
direct/effective concentration, ETF overlap, cash, staleness, coverage,
reconciliation/provider/refresh failures, dividends, explicitly defined unusual
activity, and report outcomes. There is no expression interpreter, generic
task payload, arbitrary destination configuration through MCP, prediction,
buy/sell trigger, or broker execution capability.

Owner/account-scoped rules have immutable versions and an audited
draft/active/paused/archived lifecycle. A schedule is either a fixed UTC-anchored
interval of 300..86,400 seconds or a daily UTC minute 0..1,439. Cooldown is
0..604,800 seconds. The scheduled slot defines the source cutoff. The scheduler
transaction pins a rule version and exact eligible source manifest before
inserting its evaluation job and typed `alerts.evaluate.v1` outbox. Unique
rule-version/slot identity prevents duplicate evaluations for one scheduled
slot; retries never select newer inputs. Catch-up is bounded and deferred due
slots remain durable.

Threshold episodes open on false-to-true transitions and resolve on a later
false observation. An unavailable evaluation retains its reason and cannot
clear an open condition. Continued true observations do not create duplicate
events. Acknowledgment is independent of resolution. Manual resolution does
not rearm a continuously true condition; a later false observation is required
before a subsequent true opens another episode. Superseding a rule version
closes its old episode with that explicit reason, not false evidence of recovery.
Event-based families deduplicate stable economic/run/job identity and active
revision, preserving correction links.

Cooldown suppresses notification attempts, not distinct event capture or the
in-app feed. Each evaluation records matched/not-matched/suppressed/unavailable/
failed outcome, exact metric, source references, quality, and method version.
Financial thresholds require complete material inputs by default; explicit
degraded policy preserves warning/coverage state. Health rules intentionally
evaluate stale/missing/failed states. Unknown values never become zero or a
fabricated false result.

PostgreSQL transactionally commits evaluation, episode transition, event,
in-app notification, and typed delivery outbox. The same bounded fenced
lease/retry/dead-letter policy as report jobs supports restart and duplicate
delivery. Unique event/owner notification keys provide idempotent in-app
delivery. Its feed is fully functional without external destinations.

Optional email/webhook delivery uses a separate, server-configured versioned
destination with an opaque credential reference. Missing configuration is
explicitly unavailable and never blocks evaluation. External delivery is
at-least-once with stable idempotency identity; no exactly-once claim is made
for ambiguous remote timeouts. Recheck authorization before delivery and bound
payloads/attempts. The dedicated webhook adapter requires configured HTTPS
origins, rejects redirects and private/reserved/metadata addresses including
IPv6 forms, validates every DNS answer per attempt, and pins its connection
to a validated address while retaining TLS hostname verification. These
controls follow [OWASP SSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)
(reviewed 2026-09-07). No ordinary event, error, or log contains destination
credentials, private artifact grants, raw response bodies, or signed URLs.

## Consequences

An alert can be replayed and explained from immutable inputs. Condition state,
event deduplication, acknowledgment, resolution, and delivery remain separately
inspectable, so suppression does not erase financial history. Scheduler and
worker downtime delay delivery without inventing a different calculation cutoff.
External destinations add an explicitly gated transport boundary; local
evaluation and in-app notifications remain complete without them.

Required verification includes all families, exact Decimal boundaries,
material-input gates and health exceptions, repeated slots, data correction,
cooldown/acknowledgment/manual-resolution transitions, inactive/superseded rules,
cross-owner/account denial, outbox restart, lease fencing, duplicate consumer
delivery, dead letters, missing external configuration, and webhook SSRF/DNS/
redirect rejection. This ADR accepts the design, not unexecuted test claims.

## Rejected alternatives

- Mutable active rule definitions or selecting latest data on retry: destroys
  reproducibility of historical alerts.
- Generic SQL/expression/HTTP rules: expands execution and exfiltration surfaces
  beyond bounded portfolio monitoring.
- A Redis-only schedule or notification queue: loses the authoritative job and
  evaluation state on restart/failure.
- Cooldown implemented by dropping events, or acknowledgment treated as
  recovery: hides observed history and confuses independent states.
- Requiring email/webhook setup for a working rule engine, or claiming remote
  exactly-once delivery: misrepresents local capability or transport guarantees.
