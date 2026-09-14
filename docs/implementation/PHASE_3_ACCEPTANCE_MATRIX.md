# Phase 3 Acceptance Matrix

**Status:** Accepted implementation design; runtime acceptance pending

**Inventory:** 30 local rows, ten packages, 48 mandatory scenarios

Every row requires complete local implementation plus its actual named tests and
source-bound evidence. Scenario IDs expand the predicates; completing one test
cannot substitute for the whole row. A final local pass leaves independent review
pending and does not accept production. Owner acceptance of Phase 2 applies only
to progression. No local row is blocked merely because paid/live access is absent.

| ID | Package | Acceptance predicate | Required scenarios | State |
| --- | --- | --- | --- | --- |
| P3-RISK-001 | P3-01 | Input alignment and canonical historical capture | P3-S01,P3-S02,P3-S03 | pending |
| P3-RISK-002 | P3-01 | Numerical references, PSD and edge behavior | P3-S04,P3-S05,P3-S06,P3-S07,P3-S08 | pending |
| P3-RISK-003 | P3-01 | Concentration, canonical risk views and quality | P3-S09,P3-S35 | pending |
| P3-STRESS-001 | P3-02 | Immutable scenarios, ownership and precedence | P3-S10,P3-S11 | pending |
| P3-STRESS-002 | P3-02 | Evidence-backed sensitivities and historical replay | P3-S12,P3-S13 | pending |
| P3-STRESS-003 | P3-02 | Editor/history/comparison and report parity | P3-S14,P3-S35 | pending |
| P3-PROJ-001 | P3-03 | Reproducible bounded simulation and financial conservation | P3-S15,P3-S16,P3-S17,P3-S18 | pending |
| P3-PROJ-002 | P3-03 | Goal probability, shortfall, uncertainty and sensitivity | P3-S19,P3-S20 | pending |
| P3-PROJ-003 | P3-03 | Durable admission, cancellation and restart fencing | P3-S21,P3-S22 | pending |
| P3-RESEARCH-001 | P3-04 | Exposure-ranked sources, revisions and owner workflow | P3-S23,P3-S24 | pending |
| P3-RESEARCH-002 | P3-04 | Untrusted content and optional synthesis boundaries | P3-S25 | pending |
| P3-RESEARCH-003 | P3-04 | Ownership, current licenses, export and physical retention | P3-S26 | pending |
| P3-MCP-001 | P3-05 | Real authentication and preserved/new closed registry | P3-S33,P3-S34 | pending |
| P3-MCP-002 | P3-05 | Accessible canonical resources and strict CSP | P3-S36 | pending |
| P3-MCP-003 | P3-05 | Cross-interface quality/source/value parity | P3-S35 | pending |
| P3-WEB-001 | P3-06 | Installable PWA and safe static offline behavior | P3-S37,P3-S38 | pending |
| P3-WEB-002 | P3-06 | Navigation, palette, saved layouts and account-safe selection | P3-S39 | pending |
| P3-WEB-003 | P3-06 | Measured accessibility, responsive layout and local performance | P3-S40 | pending |
| P3-PROVIDER-001 | P3-07 | Documented typed adapters and realistic replay coverage | P3-S27 | pending |
| P3-PROVIDER-002 | P3-07 | Bounded secure transport and failure policies | P3-S28 | pending |
| P3-PROVIDER-003 | P3-07 | Explicit failover, provenance, entitlements and blocked live access | P3-S29 | pending |
| P3-ACCOUNT-001 | P3-08 | Authorized aggregation, economic identity and FX | P3-S30 | pending |
| P3-ACCOUNT-002 | P3-08 | Evidenced transfer classification and degraded coverage | P3-S31 | pending |
| P3-ACCOUNT-003 | P3-08 | Canonical synthetic second broker and sealed Trading 212 | P3-S32 | pending |
| P3-OPS-001 | P3-09 | Internal adversarial coverage and artifact minimization | P3-S41,P3-S42 | pending |
| P3-OPS-002 | P3-09 | Durable failure/restart and clean synthetic restore | P3-S44,P3-S46 | pending |
| P3-OPS-003 | P3-09 | Measured load/queue/query/security and build controls | P3-S47,P3-S48 | pending |
| P3-RC-001 | P3-10 | Complete canonical journeys and preserved regressions | P3-S35,P3-S43 | pending |
| P3-RC-002 | P3-10 | Clean install, accepted Phase 2 upgrade and repeat | P3-S45 | pending |
| P3-RC-003 | P3-10 | Immutable release/evidence/provenance and honest external boundaries | P3-S48 | pending |

## Separate external gates

- Trading 212 demo credentials/smoke and actual opening-history coverage.
- Account-specific licensed provider entitlement, credentialed production access
  and any paid-provider enablement; adapter/replay tests remain local obligations.
- Production identity/secret-manager/host selection and public deployment.
- Public HTTPS/OAuth MCP and ChatGPT registration/hosted validation.
- Production backup/restore, monitoring ownership and production signing attestations.
- GitHub Actions: deferred_by_owner, unverified; no retry or billing change authorized.

These do not authorize purchases, Live, public release/tag or deployment. Retain
actual unavailable/blocked predicates individually. Do not report an implemented
adapter as a verified live integration or a local signing demonstration as a
production attestation.
