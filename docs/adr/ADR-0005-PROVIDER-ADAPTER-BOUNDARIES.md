# ADR-0005 — Provider Adapter Boundaries

**Status:** Accepted  
**Date:** 2026-08-31

## Context

Trading 212 and future market/ETF/research providers have volatile schemas, identifiers, availability, rate limits, and licenses. Letting provider types leak into the domain would make analytics brittle and block multi-provider evolution.

## Decision

All external systems are isolated behind typed capability ports and adapters. Provider DTOs, authentication, pagination, retry, rate limits, and errors stay in adapter packages. Mapping produces canonical records with provenance, coverage, and quality. Domain/analytics never call provider transports.

## Consequences

- Deterministic mock/replay adapters are mandatory.
- Unsupported semantics become explicit partial coverage.
- New providers require contract, mapping, failure, privacy/license, and operational tests.
- Provider path strings are not accepted from application/UI/MCP callers.
