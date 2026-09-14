# Phase 3 Security and Privacy

**Status:** Accepted internal threat model; executable validation pending

Assets: private finance/research/notes, credentials/JWT identities, source entitlements,
audit and jobs. Boundaries: browser/MCP host -> authenticated service -> owner-scoped
PostgreSQL -> workers/licensed transport. Ten-GET broker boundary remains sealed.
This is internal threat analysis, not external penetration-test certification.

| Threat | Required control | Evidence |
| --- | --- | --- |
| IDOR/revocation after enqueue | Current scopes/owner/account/references/license on admission, execution, reads, cursor, idempotent replay and export | P3-S26,P3-S33,P3-S34 |
| JWT identity/claim confusion | Preserve real trusted signatures/issuer/audience/identity and strict claims/IDs | P3-S33,P3-S43 |
| Prompt injection/confused deputy | Inert minimized text, distinct typed facts/notes/synthesis, no execution interpretation, model disabled | P3-S24,P3-S25 |
| SSRF/redirect/DNS/signed downloads | Fixed registry, validated/pinned public DNS, no redirects/article fetch/raw URL persistence | P3-S28,P3-S41,P3-S42 |
| Cross-owner PWA/widget leakage | Static allowlist, network-only private content, account generation guards, logout clearing | P3-S36,P3-S38 |
| Expensive work/storage/queue exhaustion | Pre-insert byte/row/work/owner quotas, bounded iterators, deadline/cancel/lease | P3-S21,P3-S22,P3-S47 |
| Stale worker/duplicate publication | Existing outbox, current grants, fencing and atomic publication | P3-S22,P3-S44 |
| Licensed derivatives after expiry | Immediate denial and bounded physical removal of inputs/checkpoints/results/reports | P3-S26,P3-S46 |
| Report formula/path/secrets | Safe rendering/download names, canonical templates, ephemeral canary scans | P3-S35,P3-S41,P3-S42 |

Exceptions expose only fixed safe categories/correlation IDs, no request/provider bodies,
queries/tokens/keys. Audit safe actor/operation/identity/digest only. Bound UTF-8 source
text; escape all presentations and reject active markup/control characters in display
identifiers. Credentials resolve through existing secret ports. Private portfolio facts
never leave to model/providers by default. API key/replay success implies no license.

Retention=min(source,run/report policy), covering every derived copy. Expiry denies
before deletion batches complete. Adversarial tests use synthetic tenants, ephemeral
keys and injected transports; retain sanitized outcomes and scanner scope/database/
version/exceptions. No real-account fixtures or production attack activity.
