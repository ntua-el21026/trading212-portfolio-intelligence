# ADR-0024: Versioned premium reports with preserved legacy contracts

**Status:** Accepted implementation decision, 2026-09-15

The owner requires complete Phase 3 reports and preservation of the original 25
MCP contracts. The existing report output has closed family/section literals and
only the `report_sections_v1` profile. Adding risk to that shared wire literal or
adding a new output union changes the old tool descriptors. Risk proof must remain
complete; it cannot be hidden, discarded or assigned an unrelated legacy family.

Use a separate premium report contract with profile `report_sections_v2` and
canonical document/context schema `2.0.0`. Versioned fixed risk tables use
`risk_*_v1`; numerical methods remain unchanged. The existing renderer, storage,
worker, transactional outbox, authorization, download grants and cleanup remain
shared. This is a wire/version boundary, not another execution system.

The six fixed report routes under `/api/v2` mirror the existing report-only route
shapes: POST `/report-jobs`, GET `/report-jobs/{job_id}`, GET `/reports`, GET
`/reports/{report_id}`, POST `/reports/{report_id}/artifacts/{artifact_id}/grants`
and GET `/reports/{report_id}/artifacts/{artifact_id}/content`. Give them distinct
premium operation IDs and typed generated clients. No new MCP tool is registered;
canonical risk remains available through its three bounded tools.

V1 API/MCP report operations select only the V1 report collection. V2 operations
select only V2. Filter at authorized SQL collection materialization, count and
cursor creation, never after reading a mixed page. Preserve V1 cursor identities
and give V2 a distinct resource/filter identity. Foreign-version direct IDs fail
before private decoding with the existing safe not-found contract. Web navigation
labels both collections explicitly and preserves account-safe selection.

Persist normalized contract metadata on report jobs/inputs, backfilling existing
records to V1 without rewriting their canonical bytes. Validate the stored version
against selection/profile before executing, reading, replaying or downloading.
V2 request framing is distinct; old selection encoding, idempotency digests and
renderer output remain unchanged when no premium section is selected. Reuse the
renderer's existing layout/version unless its visual output actually changes.

The first V2 section pins an owned succeeded immutable risk run with an exact
snapshot, reporting currency, historical window and source cutoff. Capture complete
canonical metrics, assumptions, unavailable reasons, source/proof relations and
licenses through fixed tables; never recalculate risk. A typed normalized premium
copy dependency binds subsequent reads and deletion to the run. Require current
and pinned REPORT/STORE/DISPLAY rights before decoding and recheck at every replay,
worker and download boundary. Export permissions apply to separate export contracts.

The risk inventory contains 17 fixed tables: 11 analytical tables and six proof
tables. `risk_xray_paths_v1` mirrors the existing terminal-path columns as a
separate proof table, preserving root/issuer identities, cash/unresolved reasons,
exact exposure metrics and their quality/provenance. It is empty without a pinned
X-ray run. This keeps the complete path lineage alongside an independently
selected ordinary X-ray section without reopening its analytical table. X-ray
reason notes use their named context, retaining all V1 note identities.

Clamp copy expiry to the shortest report/run/upstream/current-license deadline.
Purge dependent report artifacts before their premium source becomes physically
complete, sharing existing row/byte/metadata budgets and lock order. Keep the
32 MiB document, 2 MiB manifest, 256-license and 100,000-row table ceilings; a report
whose complete proof exceeds them fails admission rather than truncating proof.
Renderer limits also remain unchanged: 1,000 PDF pages, 10 MiB per artifact and
25 MiB total artifacts. A document admitted within the input bounds can still
fail safely during rendering if its complete layout exceeds those output bounds.
No new containers, providers, broker capabilities or paid services are required.

Before dependent implementation, capture full original tool descriptors from
`4d747f6c1281a2914c84f18a02554c18f612e249`. Regression checks compare all 25 complete
canonical descriptor hashes, including nested schemas, against that independent
baseline. Also verify unchanged legacy report bytes and mixed-version SQL routing,
source revocation, physical deletion, all four formats and API/web/risk-MCP parity.
Design acceptance does not claim implementation or local acceptance completion.
