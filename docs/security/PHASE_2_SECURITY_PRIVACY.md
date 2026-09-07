# Phase 2 Security and Privacy Extension

**Status:** Accepted

**Date:** 2026-09-07

## Boundaries and authorization

The permanent ten-capability Trading 212 GET allowlist, export URL minimization,
server-side secrets and default-deny transport remain unchanged. Targets, plans,
reports, alerts and their jobs are internal account-scoped application writes.
Their handlers have no broker dispatch dependency and cannot produce orders.

Use explicit least-privilege scopes defined in the API/MCP contracts. Authenticate
before reading private resource state. Authorize owner plus account in application
services and scoped persistence queries, including referenced snapshots, target
versions, source snapshots, jobs and artifacts. Owner-private templates may have
no account; they cannot resolve another owner's account through a later command.
Deny missing, mismatched, expired or unknown authorization uniformly without
revealing resource existence. Composite owner references and database constraints
supplement application checks; UUID unpredictability is not authorization.

Cookie commands require CSRF and trusted origin policy. Internal command payloads
reject unknown fields and impose stable bounds. Idempotency keys are scoped to
owner, account and operation; changed canonical input under the same key returns
conflict. Optimistic revision preconditions prevent lost updates. Audit content
contains actor/action/resource references, input hashes and outcomes, not raw
provider payloads, access tokens, webhook URLs, arbitrary user text or secrets.

## Outbound data and notification isolation

Follow ADR-0009. Each provider has a dedicated fixed-purpose adapter with trusted
configuration, strict schemas, maximum response bytes, timeout/retry/page/rate
budgets and redirects disabled. Never expose provider paths or arbitrary URLs
through API/MCP/plan/report inputs. Negative architecture tests preserve the
Trading 212 origin seal while permitting only named provider adapters.

Optional notification destinations are configured server-side and represented by
opaque destination IDs and secret references. Outside local tests require HTTPS,
reject credentials/fragments/unapproved ports, and resolve every address. Reject
loopback, private, link-local, unspecified, multicast, reserved and metadata ranges,
including IPv4-mapped IPv6 and mixed public/private DNS answers. Validate redirect
policy and prevent DNS rebinding between authorization and connection; never
forward credentials across origins. No delivery attempt is considered successful
without transport confirmation. Unconfigured delivery leaves in-app evaluation
working and explicitly marks external delivery unavailable.

## Reports, exports and data licenses

Artifacts are private and owner/account-bound. Safe internal IDs determine storage
keys and filenames; caller paths never do. Enforce content type, size, count and
expiry before serving; expired access fails even if cleanup has not run. Short-lived
authorized access is bound to the requesting owner and artifact. Do not persist
provider URLs or return secret-bearing locations. Keep canonical manifests and
actual byte digests separate. Audit export/download/expiry without artifact content.

Apply permitted-use/storage/display/report/export policy from each immutable source.
Denied licensed detail is withheld with explicit coverage/quality disclosure; it is
never silently exported. CSV/XLSX textual cells neutralize formula prefixes including
leading whitespace/control characters; emit no macros, executable hyperlinks,
external relationships or formulas from provider/user strings. Preserve exact values
as canonical text where a spreadsheet number would lose precision. PDF/JSON share
canonical input/method/source/quality data with the API.

## Resource and job limits

Use bounded durable collection snapshots and hard per-owner quotas inherited from
Stage A for every new collection. Expired membership cannot count as active. Bound
target tree depth/nodes, solver work, time ranges, source observations, report bytes,
rule count, dispatch batches, attempts, leases and cleanup batches. Explain capacity
failure explicitly; never return silently truncated authoritative data.

PostgreSQL commits immutable job input and outbox intent atomically. Workers use
fenced leases, bounded retries and idempotent completion. Fixed internal job kinds
cannot be supplied as a shell/SQL/function name. Retry/dead-letter records and
metrics contain sanitized categories. A restart must not duplicate financial rows,
plans, artifact completion, evaluations or notifications.

## Required negative evidence

Cross-owner/foreign-account references, missing scopes/CSRF, stale preconditions,
idempotency conflicts, mutable published inputs, malicious provider schemas,
post-cutoff data, export formulas, expired artifacts, signed-URL/secret canaries,
SSRF/DNS/redirect variants, broker-dispatch attempts and job replay must fail at the
intended boundary. Scan generated contracts, web/server bundles, compressed browser
artifacts, database records, report formats, runtime files, logs and telemetry.
Do not expose secrets in screenshots or commit real account fixtures.
