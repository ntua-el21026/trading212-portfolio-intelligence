# ADR-0002 — Monorepo with Python and TypeScript

**Status:** Accepted  
**Date:** 2026-08-31

## Context

The product combines quantitative/data/backend work with a premium web interface and ChatGPT application. One language is not optimal for both domains, while separate repositories would increase contract and release drift.

## Decision

Use one monorepo. Python 3.13 powers domain/application services, persistence, provider adapters, ingestion, analytics, API, worker, and MCP. TypeScript/Next.js/React powers the web/PWA and shared UI. Versioned OpenAPI/schema artifacts and generated clients connect them.

Use `uv` and pnpm workspaces with committed lockfiles.

## Consequences

- One commit can keep contracts, implementation, tests, docs, and UI synchronized.
- CI validates both toolchains and cross-language generated contracts.
- Financial arithmetic remains server-side/canonical; the web does presentation only.
- Repository boundaries and build commands must remain clear to avoid an unstructured monolith.
