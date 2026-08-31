# ADR-0006 — Shared Backend for Web and MCP

**Status:** Accepted  
**Date:** 2026-08-31

## Context

Separate calculations or data access for web and ChatGPT would create inconsistent portfolio values, duplicated security logic, and difficult auditing.

## Decision

HTTP API, web application, workers, reports, and MCP tools use the same canonical application services, repositories, authorization policies, and deterministic calculations. Interface layers only adapt transport and presentation.

## Consequences

- API/MCP/report parity tests use identical fixtures/parameters.
- MCP does not query SQL or Trading 212 directly.
- Web does not recalculate authoritative financial results.
- Rich ChatGPT resources remain presentation over structured tool results.
