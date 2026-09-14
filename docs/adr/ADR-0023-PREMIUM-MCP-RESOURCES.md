# ADR-0023: Closed premium MCP tools and interactive resources

**Status:** Accepted implementation decision, 2026-09-14

Extend 25 frozen tools by thirteen, including three private run-creation commands.
[The registry](../integrations/PHASE_3_MCP_TOOL_REGISTRY.md) is closed. Existing names,
inputs, auth and financial outputs remain compatible. No generic search/fetch/broker/
SQL/filesystem/execution tool. Keep Python MCP2.1.1 and dependency-free resources.

Use interactive-decoupled presentation over canonical server results. Standard MCP
Apps metadata/bridge takes precedence, tested OpenAI aliases remain compatible.
Checked 2026-09-14: [server tools](https://developers.openai.com/plugins/build/mcp-server),
[UI](https://developers.openai.com/plugins/build/chatgpt-ui),
[tool design](https://developers.openai.com/plugins/plan/tools),
[metadata](https://developers.openai.com/plugins/reference),
[examples](https://developers.openai.com/plugins/build/examples),
[MCP Apps](https://modelcontextprotocol.io/extensions/apps/overview).
The apps-sdk URLs redirected to plugins documentation; that does not justify package
migration. Preserve tested emitted metadata/MIME and real signed-JWT transport.

Widgets request only registered authorized reads after explicit user gestures. Run
creation needs explicit command/scope/semantic key, never mount-time execution.
CSP allows no remote connection/resource/frame. Validate parent/session/typed bounded
protocol payloads. Financial output remains canonical; public registration is external.
