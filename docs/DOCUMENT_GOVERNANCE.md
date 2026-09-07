# Documentation Governance

**Status:** Accepted

## 1. Purpose

Documentation is part of the executable contract. It defines product scope, financial semantics, provider boundaries, security invariants, implementation order, and acceptance evidence. Code that contradicts a higher-authority document is a defect.

## 2. Document classes

| Class | Examples | Change rule |
|---|---|---|
| Design freeze | `DESIGN_FREEZE_V0_1.md`, additive `DESIGN_FREEZE_V0_2.md` | Superseding ADR and synchronized updates required |
| ADR | `docs/adr/*` | Immutable after acceptance except typo/metadata corrections; supersede rather than rewrite decisions |
| Security/provider contract | Trading 212 contract, security architecture, allowlist | Review exact boundary and negative tests in same commit |
| Phase authority | Phase specification, technical baseline, acceptance matrix | Update before or with implementation that resolves a detail |
| Methodology | Accounting, performance, reconciliation, risk | Version calculations and fixtures with semantic changes |
| Operational | Deployment, runbooks, status | Keep synchronized with runnable commands and current evidence |
| Explanatory | README, examples, prompts | Must not conflict with higher-authority documents |

## 3. Required metadata

Normative documents should identify status and, where useful, owner, phase, or version. Valid status terms are:

- Draft
- Proposed
- Accepted
- Superseded
- Deprecated
- Implemented
- Verified

Do not use “complete,” “production-ready,” or “validated” without evidence defined by the owning acceptance matrix.

## 4. Direct-main update protocol

Because this repository uses direct commits to `main`:

1. inspect the latest `main` before editing;
2. group related documentation and contract changes coherently;
3. validate links, JSON, allowlists, and required references;
4. commit fast-forward only;
5. re-read the resulting head and CI status;
6. correct failures with a new forward commit.

## 5. Architecture decisions

Create an ADR before code depends on a consequential choice not already frozen. An ADR includes context, decision, consequences, rejected alternatives, and status. If a decision changes, add a new ADR that explicitly supersedes the old one.

## 6. External contracts

Trading 212 and OpenAI/ChatGPT are evolving external systems. For a material contract update:

- use current primary documentation;
- record verification date and source in `docs/REFERENCES.md`;
- update the human-readable contract and machine-readable allowlist together;
- update fixtures and exact/negative contract tests;
- do not probe guessed endpoints or silently tolerate semantic drift;
- preserve fail-closed behavior until verification succeeds.

## 7. Calculation methodology

A semantic change to a financial calculation requires:

- a calculation-method/version change;
- updated reference fixtures and property tests;
- migration or reproducibility analysis for stored results;
- updated methodology, API/MCP schemas, and reports;
- explicit effect on historical comparability.

## 8. Status governance

`PROJECT_PROGRESS.json` is the machine-readable implementation tracker. `PROJECT_STATUS.md` is the human-readable summary. Both must be updated when a work package starts, completes, becomes blocked, or changes external-gate status.

Allowed work-package states:

- `not_started`
- `in_progress`
- `blocked_internal`
- `blocked_external`
- `implemented_unverified`
- `complete`

## 9. Validation

`scripts/validate_repository.py` is the minimum documentation readiness gate. Phase implementation adds code, schema, migration, contract, security, and end-to-end gates; documentation validation alone never establishes application readiness.
