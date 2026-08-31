# ADR-0001 — Strictly Read-Only Product

**Status:** Accepted  
**Date:** 2026-08-31

## Context

The platform needs broker data for analysis but does not need execution to deliver its core value. Broker writes materially increase financial, security, contractual, and model-confusion risk.

## Decision

Trading 212 integration is permanently default-deny and strictly read-only under Design Freeze v0.1. Production code exposes only exact documented GET capabilities. No order/Pie mutation, money movement, arbitrary provider proxy, autonomous trading, or AI execution path exists.

A high-level application refresh command may schedule allowlisted reads; it cannot accept a broker path.

## Consequences

- Use dedicated read-only scoped credentials and optional IP restrictions.
- Add static and runtime negative tests proving writes/unknown paths are rejected before network dispatch.
- Contribution optimization returns manual plans only.
- Any future proposal to add execution requires a new design freeze and explicit risk/contract review; it is not an ordinary feature extension.
