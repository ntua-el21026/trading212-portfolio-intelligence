# ADR-0008 — Three-Phase Delivery

**Status:** Accepted  
**Date:** 2026-08-31

## Context

The intended product is broad. Building all premium features in one uncontrolled pass would increase architecture drift, financial errors, security exposure, and untestable partial implementations.

## Decision

Deliver in three gated phases:

1. **Trusted Foundation (`0.1.0`)** — canonical ingestion, history, reconciliation, core calculations, API/web/MCP foundations.
2. **Portfolio Intelligence (`0.2.0`)** — targets/Pies, optimizer, performance/benchmarks, X-ray, reports, alerts.
3. **Premium Intelligence and Productization (`1.0.0`)** — risk/scenarios/projections/goals, research, rich UI, PWA and production hardening.

A phase may introduce inert extension interfaces but may not expose later-phase functionality as complete.

## Consequences

- Each phase has a complete specification and exit checklist.
- Later phases depend on accepted earlier-phase contracts/history.
- External credential/provider gates are separated from locally executable completion.
- Scope discoveries are assigned deliberately rather than absorbed opportunistically.
