# ADR-0007 — Direct Commits to Main

**Status:** Accepted by repository owner  
**Date:** 2026-08-31

## Context

The repository owner requires both ChatGPT and Codex to commit implementation and documentation directly to `main` rather than use branches or pull requests.

## Decision

All work uses small coherent fast-forward commits directly on `main`.

Rules:

- read/synchronize current `main` before work and before each commit;
- run all relevant required gates before committing;
- never force-push, reset, rebase shared history, or rewrite commits;
- correct a failing main immediately with a new coherent commit;
- keep documentation/progress synchronized;
- avoid concurrent unsynchronized agents writing overlapping files;
- use conventional commit messages.

## Consequences

- Local validation and small commits are mandatory because CI runs after the commit reaches `main`.
- Codex must inspect for concurrent changes before committing.
- GitHub branch/PR templates are not part of the delivery workflow.
- Release evidence references exact main SHAs.
