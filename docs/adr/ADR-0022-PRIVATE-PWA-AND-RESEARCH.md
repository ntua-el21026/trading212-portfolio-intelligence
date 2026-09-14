# ADR-0022: Private PWA shell and untrusted research

**Status:** Accepted implementation decision, 2026-09-14

Cache only an explicit public static-shell allowlist. Account HTML/APIs/reports,
OAuth, headers and tokens never enter offline persistence. Offline navigation shows
public unavailability. Saved layouts live in owner-scoped PostgreSQL; widget state
contains only presentation. Clear old results before any account/owner change.

Fixed providers acquire research; fetched text remains inert data, never instructions,
HTML, tools or destinations. Typed source facts, canonical portfolio facts and owner
revisions work without synthesis. External synthesis is disabled/unavailable until
separately configured; minimized authorized citations cannot mint finance or disclose
private portfolio data by default. No model call is required for local completion.

Controls: [security](../security/PHASE_3_SECURITY_PRIVACY.md) and
[web architecture](../architecture/PHASE_3_WEB_INFORMATION_ARCHITECTURE.md).
