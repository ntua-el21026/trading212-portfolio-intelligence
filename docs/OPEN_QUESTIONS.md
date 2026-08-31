# Open Questions and External Validation Gates

**Status:** Accepted tracking document

No unresolved item below blocks Phase 1 architecture or local implementation. Items are resolved when their external evidence becomes available and must not be guessed.

| ID | Question / gate | Safe default | Resolution evidence | Blocks |
|---|---|---|---|---|
| OQ-001 | Exact Trading 212 Demo payload variations for the user's account | Strict schema with retained unknown fields; fixtures based on official contract; fail visibly on incompatible payload | Sanitized Demo contract/smoke run | Claiming live Demo integration complete |
| OQ-002 | Effective endpoint-specific rate-limit behavior under the account | Central limiter with conservative policy and response-header adaptation | Demo observations and recorded headers | Production tuning, not local adapter implementation |
| OQ-003 | Complete historical coverage available from Trading 212 transactions/orders/dividends | Report coverage window; never infer missing history as zero | First full Demo/Live read-only ingestion | Historical metric coverage claims |
| OQ-004 | Production hosting provider and region | Provider-neutral Docker deployment; EU region preferred | User deployment decision | Remote deployment only |
| OQ-005 | Authentication identity provider for remote web/MCP production | Local development auth plus adapter boundary; fail closed in production | User deployment decision | Public remote production access |
| OQ-006 | Production secret manager | Environment injection in local dev; deployment secret-manager interface | Hosting decision | Production credential installation |
| OQ-007 | External market and ETF constituent data provider | No Phase 1 dependency; provider contracts only | Phase 2 provider evaluation | Phase 2 X-ray/performance breadth |
| OQ-008 | Retention duration for raw broker payloads and private exports | Minimize by default; configurable retention; no public storage | User privacy/operations decision | Production retention policy finalization |
| OQ-009 | ChatGPT MCP deployment URL and OAuth/auth configuration | Authenticated local/contract tests; no unauthenticated remote endpoint | Deployed domain and ChatGPT developer configuration | Live ChatGPT invocation |

## Resolution process

For each resolved item:

1. Record date, evidence, and decision.
2. Update the owning contract/specification.
3. Add an ADR when architecture or security posture changes.
4. Add/update fixtures without private account data.
5. Update `PROJECT_STATUS.md` and `PROJECT_PROGRESS.json` where the acceptance state changes.

## Prohibited assumptions

Codex must not invent credentials, account payloads, paid-provider entitlements, domains, tax rules, or production hosting configuration. Implement safe adapters, mocks, and explicit external gates instead.
