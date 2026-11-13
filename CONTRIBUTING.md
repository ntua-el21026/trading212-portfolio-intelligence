# Contributing

This public repository retains its [proprietary license](LICENSE.md). Contributions
require the repository owner's authorization; source visibility does not change
copyright or redistribution rights. The development workflow applies to the owner
and authorized contributors, including agent-assisted sessions.

## Workflow

The owner has selected direct commits to `main`:

1. Read `AGENTS.md` and `docs/DESIGN_INDEX.md`.
2. Synchronize and inspect current `main`.
3. Make one coherent change.
4. Update tests, documentation, and project progress in the same change.
5. Run all relevant required gates.
6. Review for secrets, private data, generated noise, and phase-scope violations.
7. Commit directly to `main` with a conventional message.
8. Never force-push, rebase/reset shared history, create implementation branches, or open pull requests.

Concurrent agents must not edit overlapping files without first reconciling the latest `main`.

Recommended GitHub ruleset (not claimed configured): permit direct pushes to
`main`, block force pushes and branch deletion, require linear history, and do
not require pull requests. Signed commits may be required only after signing is
configured. On 2026-09-07, GitHub's rulesets API returned HTTP 403 for the
then-private repository's plan/entitlement; hosted ruleset configuration remains a non-blocking
external governance action. Local and CI governance validation continue to enforce
the main-only workflow independently.
No task-local example, release procedure, or historical record authorizes an alternate
delivery path.

## Required invariants

- Trading 212 remains strictly GET-only/default-deny.
- No execution/order/Pie mutation/generic provider proxy.
- Exact decimal money and UTC timestamps.
- Deterministic versioned calculations with provenance/quality.
- Provider DTOs isolated from canonical domain.
- Secrets/private account data never committed or logged.
- Current phase boundaries respected.
- Status/progress never overstated.

## Commit messages

Use conventional, specific messages:

```text
feat(domain): add exact currency-aware money values
feat(trading212): implement allowlisted positions read
fix(reconciliation): preserve unmatched activity residual
 test(security): reject unknown broker capability
 docs: record P1-04 acceptance evidence
```

## Documentation changes

Architecture, contract, calculation, security, and scope changes require updates to the owning document. Add an ADR before depending on a consequential architectural deviation. Keep `docs/DESIGN_INDEX.md`, `PROJECT_STATUS.md`, and `PROJECT_PROGRESS.json` synchronized.

## Quality

The authoritative commands are established during P1-01 and exposed through the root Makefile. A commit is not ready when required format, lint, type, test, security, migration, documentation, or build gates fail.

External credentials may skip only clearly marked Demo/deployment tests. They are not justification to skip mock, contract, negative-security, or deterministic calculation tests.

## Private data

Use synthetic fixtures. Do not commit:

- API keys/secrets/tokens/cookies;
- real account IDs, balances, positions, activity, reports, or screenshots;
- production database dumps;
- private logs/traces;
- local `.env` files;
- generated exports containing portfolio data.
