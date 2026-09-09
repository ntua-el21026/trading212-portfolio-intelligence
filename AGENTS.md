# Repository Agent Policy

This file applies to every human, ChatGPT, Codex, and automated agent working in this repository.

## 1. Source of truth

Treat the current `main` branch as the source of truth. Before changing anything:

1. synchronize and record the starting SHA;
2. inspect the repository tree and recent history;
3. read `docs/DESIGN_INDEX.md` and the active phase authority documents;
4. verify that no newer direct-to-`main` commit changes the assumptions for the next commit.

Document precedence is defined in `docs/DESIGN_INDEX.md`. Do not silently resolve a conflict in favor of a lower-authority document.

## 2. Required Git workflow

The owner has explicitly selected direct development on `main`.

- Commit directly to `main`.
- Do not create branches or pull requests.
- Task-local examples, historical delivery records, and command snippets do not override this
  main-only workflow.
- Use small, coherent, fast-forward commits.
- Synchronize and re-read `main` immediately before each commit.
- Never force-push, reset shared history, amend published commits, or rewrite history.
- Use Conventional Commit-style messages.
- Leave `main` runnable and honest after every commit.

## 3. Permanent product boundary

The application is strictly read-only with respect to Trading 212.

- Only the capabilities in `config/contracts/trading212-read-allowlist.yaml` may dispatch.
- Every broker request is `GET` and uses a fixed, typed path template.
- There is no public or generic `request(method, path)` API.
- No order placement, cancellation, amendment, Pie mutation, transfer, CFD operation, or other broker write may be implemented.
- Unknown methods, paths, parameters, and capabilities must fail before network dispatch.
- Demo is the default environment. Live requires explicit read-only configuration.
- Contribution or rebalancing output is a manual proposal, never execution.

## 4. Financial correctness

- Use exact decimal representations for money, quantity, prices, FX, ratios, and authoritative calculations.
- Never construct an authoritative decimal from a binary float.
- Every monetary value has an explicit currency.
- Cross-currency calculations require an explicit sourced FX rate.
- Internal timestamps are timezone-aware UTC.
- Missing, zero, stale, partial, estimated, unreconciled, unavailable, and failed are distinct states.
- Deposits and withdrawals are external cash flows; purchases and sales are internal portfolio flows.
- Provider-reported and internally derived values remain distinguishable.
- Every material result carries methodology/version, valuation/source time, provenance, coverage, quality, and warnings.

## 5. Security and privacy

- Credentials remain server-side and outside source control.
- Do not print, log, trace, serialize, return, screenshot, or persist secrets in ordinary application data.
- Use synthetic data in committed fixtures.
- Authentication and authorization fail closed outside local/test mode.
- Account-scoped operations require owner/account authorization.
- API, MCP, and web interfaces expose bounded typed operations only.
- Add negative tests and secret-canary tests for security boundaries.

## 6. Engineering standard

Implement complete vertical capabilities, not misleading placeholders. A command must not report success while doing nothing. Keep migrations, generated contracts, tests, documentation, status, and code synchronized.

Before a coherent commit, run all relevant formatting, linting, typing, unit, property, contract, integration, migration, security, build, documentation, and end-to-end checks that exist at that stage.

## 7. Status and evidence

Update `PROJECT_PROGRESS.json` and `PROJECT_STATUS.md` whenever implementation state materially changes. Mark work complete only with concrete evidence. External credentials or deployment gates may remain explicitly blocked; never fabricate their validation.

## 8. Stopping conditions

Continue autonomously through locally resolvable work. Stop only for:

- a genuine conflict between higher-authority requirements;
- a required external credential, domain, or provider decision that cannot be safely represented by an adapter/mock/gate;
- an unavailable required tool after reasonable documented alternatives are exhausted;
- a requested change that would violate the read-only or security freeze.

When blocked, commit completed coherent work, keep `main` passing, state the exact blocker and evidence, and identify the smallest next action.

## 9. Local resource and disk housekeeping

Keep laptop verification serial and reuse one task Compose project. Start only
the services a check needs; use one container when sufficient. Reuse those
services across checks instead of creating a new stack for each attempt.

At verification boundaries, inspect and remove task-owned disposable artifacts
that are no longer needed: stopped containers, disposable test volumes and
networks, obsolete build records/cache, inactive Next development outputs, and
installer archives whose extracted tools are already verified. Remove the task
stack and its disposable metadata when runtime verification finishes.

Check for active consumers before deleting generated outputs. Preserve source,
uncommitted work, required dependencies and tools, accepted evidence, and current
handoffs. Scope cleanup to inspected task-owned paths or Docker identifiers;
never use global pruning or delete unrelated volumes and user data.
