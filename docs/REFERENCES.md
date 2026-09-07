# Primary External References

**Last reviewed:** 2026-09-07 (historical export schema; other references retain prior review)

Primary sources are authoritative for external contracts. The application must fail closed when a beta provider contract cannot be verified.

## Trading 212

- Public API overview and environments: https://docs.trading212.com/
- OpenAPI/API reference: https://docs.trading212.com/api/
- Rate limiting: https://docs.trading212.com/api/section/rate-limiting/
- Account summary: https://docs.trading212.com/api/accounts/getaccountsummary
- Positions: https://docs.trading212.com/api/portfolio/positions
- Pending orders: https://docs.trading212.com/api/orders/pending
- Historical orders: https://docs.trading212.com/api/historical-events/orders_1
- Historical transactions: https://docs.trading212.com/api/historical-events/transactions
- Historical dividends: https://docs.trading212.com/api/historical-items/dividends
- Historical exports: https://docs.trading212.com/api/historical-events/getreports
- API-key help: https://helpcentre.trading212.com/hc/en-us/articles/14584770928157-Trading-212-API-key

Endpoint names/slugs on the documentation website may move; verify the official OpenAPI before implementing P1-04. The frozen relative-path templates are maintained in the Trading 212 contract and machine allowlist.

The historical export response was rechecked against the official
[List generated reports reference](https://docs.trading212.com/api/historical-events/getreports)
on 2026-09-07. Its status enum is `Queued`, `Processing`, `Running`, `Canceled`,
`Failed`, or `Finished`; `dataIncluded` defines the boolean flags
`includeDividends`, `includeInterest`, `includeOrders`, and `includeTransactions`.
The audit correction retains these selected semantics and download availability
without retaining or following `downloadLink`. No dispatch capability changed.

## OpenAI / ChatGPT Apps and MCP

- Developer mode and custom MCP apps: https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt-beta
- Apps SDK overview: https://help.openai.com/en/articles/12515353-build-with-the-apps-sdk
- Apps SDK documentation: https://developers.openai.com/apps-sdk/
- Model Context Protocol: https://modelcontextprotocol.io/

Verify current ChatGPT plan/surface limitations before remote registration. Local MCP implementation, authentication, schema tests, and mock-data flows must not depend on registration availability.

## Runtime platforms

- Python releases: https://www.python.org/downloads/
- Node.js releases: https://nodejs.org/en/about/previous-releases
- PostgreSQL current releases: https://www.postgresql.org/support/versioning/
- Redis releases: https://redis.io/downloads/
- Celery documentation: https://docs.celeryq.dev/

`PHASE_1_TECHNICAL_BASELINE.md` records the selected compatibility baseline; P1-01 locks exact dependency versions after verifying primary documentation and compatibility.
