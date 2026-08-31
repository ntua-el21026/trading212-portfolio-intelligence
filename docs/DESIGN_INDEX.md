# Design Index and Authority Order

**Status:** Accepted  
**Design freeze:** v0.1  
**Implementation branch:** `main`

This file is the entry point for architecture, implementation, and review.

## 1. Authority and precedence

When documents conflict, apply this order from highest to lowest authority:

1. Explicit owner instruction in the current task.
2. `AGENTS.md` repository operating and safety policy.
3. `docs/DESIGN_FREEZE_V0_1.md`.
4. Accepted ADRs under `docs/adr/`.
5. Security and external-provider contracts:
   - `docs/security/SECURITY_ARCHITECTURE.md`
   - `docs/integrations/TRADING212_API_CONTRACT.md`
   - `config/contracts/trading212-read-allowlist.yaml`
6. Active phase authorities:
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
- `SECURITY.md`
- `CONTRIBUTING.md`

## 8. Delivery and handoff

- `docs/implementation/MASTER_IMPLEMENTATION_PLAN.md`
- `docs/implementation/PHASE_1_TRUSTED_FOUNDATION.md`
- `docs/implementation/PHASE_2_PORTFOLIO_INTELLIGENCE.md`
- `docs/implementation/PHASE_3_PREMIUM_PRODUCTIZATION.md`
- `docs/implementation/PHASE_1_TECHNICAL_BASELINE.md`
- `docs/implementation/PHASE_1_EXECUTION_MANIFEST.md`
- `docs/implementation/PHASE_1_ACCEPTANCE_MATRIX.md`
- `docs/implementation/PHASE_1_READINESS_REVIEW.md`
- `docs/implementation/prompts/PHASE_1_CODEX_PROMPT.md`
- `VALIDATION_REPORT.md`

## 9. Change control

A change to a frozen invariant requires an accepted superseding ADR and synchronized updates to every affected authority, test contract, status file, and prompt. External beta API drift must be verified against primary provider documentation and changed deliberately; automatic endpoint probing is prohibited.
