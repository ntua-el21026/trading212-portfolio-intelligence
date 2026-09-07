# Provider Adapter Strategy

**Status:** Accepted

## Purpose

External systems change independently, use incompatible identifiers, have incomplete coverage, and fail in provider-specific ways. Provider adapters isolate those facts from the canonical portfolio model and deterministic analytics.

## Required provider ports

### Phase 1

- `BrokerAccountDataProvider`
- `SecretProvider`
- `Clock`
- optional job/lock/cache ports

### Phase 2

The concrete capability, transport, bounds and licensing contract is
[Phase 2 Provider Contracts](PHASE_2_PROVIDER_CONTRACTS.md). The accepted
[transport ADR](../adr/ADR-0009-PROVIDER-TRANSPORT-ISOLATION.md) preserves the
separate Trading 212 origin seal.

- `MarketPriceHistoryProvider`
- `FxReferenceProvider`
- `BenchmarkProvider`
- `ETFConstituentProvider`
- `ReportStorageProvider`
- `NotificationProvider`

### Phase 3

- `ResearchSourceProvider`
- optional advanced reference/classification providers

## Adapter rules

1. Provider DTOs remain inside the adapter package.
2. Mapping produces canonical records plus provenance, coverage, and confidence.
3. Provider-specific error codes map to stable application categories.
4. Every network adapter has explicit timeout, retry, rate, pagination, and payload-size policies.
5. Secrets are injected by opaque reference and redacted centrally.
6. Provider implementations can be replaced with deterministic fixtures.
7. No provider is accessed from domain or calculation code.
8. Unsupported semantics produce explicit partial coverage, not synthetic data.
9. Data-license restrictions are represented in configuration and export behavior.
10. Cached provider data retains source timestamp/version and cannot be presented as newly observed.

## Capability declaration

Each provider implementation declares:

- provider name and adapter version;
- supported capability enums;
- environment/region;
- source freshness characteristics;
- pagination and rate-limit model;
- identifier coverage;
- license/export restrictions;
- health state;
- schema/contract version.

Application services request capabilities, never provider paths.

## Mock provider

The repository must ship a deterministic synthetic provider that supports:

- complete happy-path portfolio;
- empty account;
- multi-currency account;
- fractional positions;
- deposits, withdrawals, buys, sells, fees, dividends, and unknown activity;
- partial history;
- duplicate and updated records;
- unmapped instrument;
- malformed schema;
- rate limiting, transient errors, permanent errors, and pagination loops;
- clock/freshness control.

This provider powers local demos and end-to-end tests without real credentials.

## Adding a provider

A provider is not accepted until it has:

- documented capability/coverage mapping;
- threat/privacy/license review;
- strict DTO schemas;
- canonical mapping tests;
- error/retry/rate/pagination tests;
- replayable sanitized fixtures;
- data-quality behavior;
- operational telemetry;
- no changes required to core financial algorithms for provider field names.
