# Design Index and Authority Order

**Status:** Accepted  
**Design freeze:** v0.1 foundation, v0.2 Phase 2 delta and v1.0 Phase 3 delta

**Implementation branch:** `main`

This file is the entry point for architecture, implementation, and review.

## 1. Authority and precedence

When documents conflict, apply this order from highest to lowest authority:

1. Explicit owner instruction in the current task.
2. `AGENTS.md` repository operating and safety policy.
3. `docs/DESIGN_FREEZE_V0_1.md` and its additive deltas `docs/DESIGN_FREEZE_V0_2.md` and `docs/DESIGN_FREEZE_V1_0.md`.
4. Accepted ADRs under `docs/adr/`.
5. Security and external-provider contracts:
   - `docs/security/SECURITY_ARCHITECTURE.md`
   - `docs/integrations/TRADING212_API_CONTRACT.md`
   - `config/contracts/trading212-read-allowlist.yaml`
6. Active phase authorities:
   - `docs/implementation/PHASE_2_TECHNICAL_BASELINE.md`
   - `docs/implementation/PHASE_2_EXECUTION_MANIFEST.md`
   - `docs/implementation/PHASE_2_ACCEPTANCE_MATRIX.md`
   - `docs/implementation/PHASE_2_SCENARIO_EVIDENCE.md`
   - `docs/implementation/PHASE_1_TECHNICAL_BASELINE.md`
   - `docs/implementation/PHASE_1_TRUSTED_FOUNDATION.md`
   - `docs/implementation/PHASE_1_EXECUTION_MANIFEST.md`
   - `docs/implementation/PHASE_1_ACCEPTANCE_MATRIX.md`
7. System, domain, data, analytics, API, MCP, privacy, test, and operations specifications.
8. Product requirements and scope documents.
9. README, examples, explanatory notes, and prompts.

`PHASE_1_TECHNICAL_BASELINE.md` is authoritative for Phase 1 runtime/toolchain versions and supersedes older version examples elsewhere. The machine-readable Trading 212 allowlist and its human-readable contract must agree; any disagreement blocks implementation until corrected.

## 2. Required reading for Phase 1

Read in this order:

1. `AGENTS.md`
2. `README.md`
3. `docs/DESIGN_FREEZE_V0_1.md`
4. `docs/DOCUMENT_GOVERNANCE.md`
5. `docs/PRODUCT_REQUIREMENTS.md`
6. `docs/SCOPE_AND_NON_GOALS.md`
7. `docs/SYSTEM_ARCHITECTURE.md`
8. `docs/architecture/DOMAIN_AND_DATA_MODEL.md`
9. `docs/architecture/API_AND_SERVICE_CONTRACTS.md`
10. `docs/architecture/BACKGROUND_JOBS_AND_INGESTION.md`
11. `docs/integrations/TRADING212_API_CONTRACT.md`
12. `docs/integrations/CHATGPT_MCP_APP.md`
13. `docs/integrations/PROVIDER_ADAPTERS.md`
14. `docs/analytics/FINANCIAL_CALCULATION_POLICY.md`
15. `docs/analytics/PERFORMANCE_ACCOUNTING.md`
16. `docs/analytics/DATA_QUALITY_AND_RECONCILIATION.md`
17. `docs/security/SECURITY_ARCHITECTURE.md`
18. `docs/security/PRIVACY_RETENTION_AUDIT.md`
19. `docs/engineering/ENGINEERING_STANDARDS.md`
20. `docs/engineering/TEST_STRATEGY.md`
21. `docs/engineering/DEPLOYMENT_OPERATIONS.md`
22. `docs/implementation/MASTER_IMPLEMENTATION_PLAN.md`
23. `docs/implementation/PHASE_1_TECHNICAL_BASELINE.md`
24. `docs/implementation/PHASE_1_TRUSTED_FOUNDATION.md`
25. `docs/implementation/PHASE_1_EXECUTION_MANIFEST.md`
26. `docs/implementation/PHASE_1_ACCEPTANCE_MATRIX.md`
27. `docs/implementation/PHASE_1_READINESS_REVIEW.md`
28. every accepted ADR under `docs/adr/`
29. `PROJECT_STATUS.md`
30. `PROJECT_PROGRESS.json`

## 3. Product and scope

- `docs/PRODUCT_REQUIREMENTS.md`
- `docs/SCOPE_AND_NON_GOALS.md`
- `docs/OPEN_QUESTIONS.md`
- `docs/REQUIREMENTS_TRACEABILITY.md`

## 4. Architecture and data

- `docs/SYSTEM_ARCHITECTURE.md`
- `docs/architecture/DOMAIN_AND_DATA_MODEL.md`
- `docs/architecture/API_AND_SERVICE_CONTRACTS.md`
- `docs/architecture/BACKGROUND_JOBS_AND_INGESTION.md`

## 5. Integrations

- `docs/integrations/TRADING212_API_CONTRACT.md`
- `config/contracts/trading212-read-allowlist.yaml`
- `docs/integrations/CHATGPT_MCP_APP.md`
- `docs/integrations/PROVIDER_ADAPTERS.md`

## 6. Financial and analytical methodology

- `docs/analytics/FINANCIAL_CALCULATION_POLICY.md`
- `docs/analytics/PERFORMANCE_ACCOUNTING.md`
- `docs/analytics/DATA_QUALITY_AND_RECONCILIATION.md`
- `docs/analytics/ALLOCATION_DRIFT_OPTIMIZER.md`
- `docs/analytics/PORTFOLIO_XRAY.md`
- `docs/analytics/RISK_STRESS_AND_PROJECTIONS.md`

The last three are primarily Phase 2/3 authorities and must not be represented as Phase 1 production functionality.

## 7. Security, privacy, engineering, and operations

- `docs/security/SECURITY_ARCHITECTURE.md`
- `docs/security/PRIVACY_RETENTION_AUDIT.md`
- `docs/engineering/ENGINEERING_STANDARDS.md`
- `docs/engineering/TEST_STRATEGY.md`
- `docs/engineering/DEPLOYMENT_OPERATIONS.md`
- `docs/operations/LOCAL_AND_DEPLOYMENT.md`
- `docs/operations/BACKUP_RESTORE.md`
- `docs/operations/CREDENTIALS_AND_DEMO_VALIDATION.md`
- `docs/operations/MCP_CHATGPT_VALIDATION.md`
- `docs/operations/TROUBLESHOOTING.md`
- `SECURITY.md`
- `CONTRIBUTING.md`

## 8. Delivery and handoff

- `docs/implementation/MASTER_IMPLEMENTATION_PLAN.md`
- `docs/implementation/PHASE_1_TRUSTED_FOUNDATION.md`
- `docs/implementation/PHASE_2_PORTFOLIO_INTELLIGENCE.md`
- `docs/implementation/PHASE_3_PREMIUM_PRODUCTIZATION.md`
- `docs/implementation/PHASE_1_TECHNICAL_BASELINE.md`
- `docs/implementation/P1_01_DEPENDENCY_BASELINE.md`
- `docs/implementation/PHASE_1_EXECUTION_MANIFEST.md`
- `docs/implementation/PHASE_1_ACCEPTANCE_MATRIX.md`
- `docs/implementation/PHASE_1_READINESS_REVIEW.md`
- `docs/implementation/prompts/PHASE_1_CODEX_PROMPT.md`
- `VALIDATION_REPORT.md`

## 9. Change control

A change to a frozen invariant requires an accepted superseding ADR and synchronized updates to every affected authority, test contract, status file, and prompt. External beta API drift must be verified against primary provider documentation and changed deliberately; automatic endpoint probing is prohibited.

## Phase 2 accepted execution contracts

Phase 1 is accepted at `99df47b6633791c3900a52f46f56d48be922a436`. Phase 2 design
acceptance authorizes implementation, not runtime completion. Read the v0.2 delta,
ADRs 0009–0016, the narrow [ADR-0017](adr/ADR-0017-DECIMAL256-EXACT-XRAY.md) X-ray amendment,
technical baseline and manifest before depending on the new choices.

- [Data model](architecture/PHASE_2_DATA_MODEL.md)
- [API and service contracts](architecture/PHASE_2_API_SERVICE_CONTRACTS.md)
- [Provider contracts](integrations/PHASE_2_PROVIDER_CONTRACTS.md)
- [Financial, reporting and alert methods](analytics/PHASE_2_METHODS.md)
- [MCP registry](integrations/PHASE_2_MCP_TOOL_REGISTRY.md)
- [Web information architecture](architecture/PHASE_2_WEB_INFORMATION_ARCHITECTURE.md)
- [Security and privacy](security/PHASE_2_SECURITY_PRIVACY.md)
- [Test strategy](engineering/PHASE_2_TEST_STRATEGY.md)
- [Operations](operations/PHASE_2_OPERATIONS.md)

Phase 1's sealed broker boundary and immutable audit evidence remain authoritative.
Phase 2 is accepted by the owner for progression at corrected source f88b019,
delivered at d2ebdaf. Phase 3 design preparation and execution are authorized;
its local completion and independent acceptance remain pending. See
[ADR-0018](adr/ADR-0018-OWNER-AUTHORIZED-PHASE-TRANSITION.md) and the
[owner decision](implementation/evidence/phase-3-owner-authorization-20260914.json).
The additive Phase 3 freeze must precede dependent product implementation.

## Phase 3 accepted execution contracts

The owner authorizes implementation of all ten packages. Design acceptance does not
certify runtime completion, independent acceptance, deferred CI or production. Read:

- [DESIGN FREEZE V1 0](DESIGN_FREEZE_V1_0.md)
- [PHASE 3 METHODS](analytics/PHASE_3_METHODS.md)
- [PHASE 3 API SERVICE CONTRACTS](architecture/PHASE_3_API_SERVICE_CONTRACTS.md)
- [PHASE 3 DATA MODEL](architecture/PHASE_3_DATA_MODEL.md)
- [PHASE 3 WEB INFORMATION ARCHITECTURE](architecture/PHASE_3_WEB_INFORMATION_ARCHITECTURE.md)
- [PHASE 3 TEST STRATEGY](engineering/PHASE_3_TEST_STRATEGY.md)
- [PHASE 3 ACCEPTANCE MATRIX](implementation/PHASE_3_ACCEPTANCE_MATRIX.md)
- [PHASE 3 EXECUTION MANIFEST](implementation/PHASE_3_EXECUTION_MANIFEST.md)
- [PHASE 3 IMPLEMENTATION REPORT](implementation/PHASE_3_IMPLEMENTATION_REPORT.md)
- [PHASE 3 SCENARIO EVIDENCE](implementation/PHASE_3_SCENARIO_EVIDENCE.md)
- [PHASE 3 TECHNICAL BASELINE](implementation/PHASE_3_TECHNICAL_BASELINE.md)
- [PHASE 3 MCP TOOL REGISTRY](integrations/PHASE_3_MCP_TOOL_REGISTRY.md)
- [PHASE 3 PROVIDER CONTRACTS](integrations/PHASE_3_PROVIDER_CONTRACTS.md)
- [PHASE 3 OPERATIONS](operations/PHASE_3_OPERATIONS.md)
- [PHASE 3 SECURITY PRIVACY](security/PHASE_3_SECURITY_PRIVACY.md)
- [ADR-0019-PREMIUM-NUMERICAL-METHODS](adr/ADR-0019-PREMIUM-NUMERICAL-METHODS.md)
- [ADR-0020-PREMIUM-DURABLE-WORK](adr/ADR-0020-PREMIUM-DURABLE-WORK.md)
- [ADR-0021-PREMIUM-PROVIDERS-AND-LICENSES](adr/ADR-0021-PREMIUM-PROVIDERS-AND-LICENSES.md)
- [ADR-0022-PRIVATE-PWA-AND-RESEARCH](adr/ADR-0022-PRIVATE-PWA-AND-RESEARCH.md)
- [ADR-0023-PREMIUM-MCP-RESOURCES](adr/ADR-0023-PREMIUM-MCP-RESOURCES.md)
- [ADR-0024-VERSIONED-PREMIUM-REPORTS](adr/ADR-0024-VERSIONED-PREMIUM-REPORTS.md)
