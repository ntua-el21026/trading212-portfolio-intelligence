# ADR-0009 — Phase 1 Review-Branch Exception

**Status:** Proposed for owner approval
**Date:** 2026-09-01

## Context

ADR-0007 establishes direct commits to `main`. The owner's complete Phase 1 execution request instead names `codex/phase-1-trusted-foundation` as the required branch, explicitly prohibits implementation on `main`, and requires a review-only pull request that Codex must not merge. Those instructions cannot both be followed for the same release candidate.

## Proposed decision

Apply a one-release exception for the Phase 1 `0.1.0` candidate:

- retain the documentation baseline on `main` unchanged while implementation is reviewed;
- use only `codex/phase-1-trusted-foundation` for Phase 1 implementation commits;
- require conventional, logically separated commits and the complete release evidence on the branch;
- open one pull request against `main` titled `feat: implement Phase 1 trusted foundation`;
- do not self-merge, force-push, or rewrite published history;
- require owner review before any merge.

ADR-0007 remains the general repository policy unless the owner accepts a broader workflow change. This proposed ADR records only the explicit Phase 1 exception and does not silently rewrite the accepted decision.

## Consequences

- CI and review occur before Phase 1 reaches `main`.
- The implementation report and final response must identify the branch, pull request, and immutable head SHA.
- Any merge remains an owner action outside this implementation task.
- If the owner rejects this exception, the pull request remains unmerged and the direct-main policy remains authoritative.
