# LOCAL/DEMO acceptance and documentation consolidation — 17 November 2026

**Status:** Completed documentation consolidation of the owner-accepted milestone.
**Owner:** Michail Athanasios Peppas.
**Starting and accepted implementation snapshot:** `cd2ff67be870983b4a321d49b8d33bdc68d8ed2d`.
**Scope:** Documentation and scoped status metadata only; no new implementation.

Trading 212 Portfolio Intelligence is an owner-accepted, architecture-frozen
LOCAL/DEMO software-engineering portfolio project with a professionally documented
implementation and explicitly bounded qualification. Formal project closure
remains an owner decision after review of this consolidation.

## Acceptance and evidence

The [owner acceptance record](LOCAL_DEMO_ACCEPTANCE_20261117.md) and
[machine-readable decision](evidence/local-demo-owner-acceptance-20261117.json)
record acceptance on 17 November at the reviewed snapshot. The coordinator's
owner-reported independent executions comprise 981 frontend unit tests, 55 focused
frontend regressions and two fixture-clock tests, with scoped frontend typecheck,
lint and documentation checks passing. The review verified six implementation
commits, the source inventory and boundaries, genuine screenshots, and the retained
archive SHA-256 and all 481 members. These are reported review results, not new
executions in this documentation task. Broader browser/database suites were not
independently rerun by that review.

The [architecture freeze](../DESIGN_FREEZE_LOCAL_DEMO_20261117.md) captures the
implemented system: shared Python/TypeScript boundaries, PostgreSQL authority,
Redis/Celery/outbox responsibilities, seven long-running and two one-shot Compose
services, 38 MCP tools/11 resources, the sealed ten-GET provider adapter, financial
and privacy invariants, 32 page routes, and light/dark/system appearance. It is
additive to the earlier freezes and accepted ADRs. Material future architecture
changes require an explicit new owner decision and the established ADR process.

The two status JSON files change only their identical `local_demo_milestone`
objects. Their schema version, Phase 3 state, candidate/evidence objects, historical
source identifiers and formal acceptance counts are unchanged. All formal matrix
and scenario table rows retain their earlier evidence and pending disposition.

## Editorial and reader-facing changes

The README now presents the engineering problem, implemented capabilities,
architecture, financial/data-quality/security methodology, scoped evidence, exact
source-defined setup commands, and a curated reading guide. It uses three existing
genuine synthetic captures: desktop Overview in light and dark side by side, with
Mobile Holdings below. Original image bytes and the provenance manifest remain
unchanged; the tablet capture remains available through that manifest.

The [design index](../DESIGN_INDEX.md) leads readers from architecture to financial
methodology, security, local operation and evidence. The v0.1 architecture remains
an identified foundation contract; older UI specifications, roadmap and prompt are
classified as historical development provenance. Dated qualification reports
retain failures and source qualifications. Operations/test documents distinguish
the accepted demonstration from broader Phase 3 obligations. No earlier accepted
freeze, ADR, security policy, scanner rule or licensing text is rewritten.

## Bounded checks executed during consolidation

These observations use the accepted commit as their parent and the recorded
working-tree identity. Receipts retain exact commands, exits, durations and source
state. They do not represent a new complete application validation.

| Command/check | Actual result | Elapsed | Qualification |
| --- | --- | --- | --- |
| `make docs-check` — initial | Exit 2 | 7.738 s | README lacked two mandatory direct-main governance phrases; failure retained. |
| `make docs-check` — focused recovery | Exit 0 | 7.184 s | Required README maintenance note restored; 105 required files, ten GETs, 25 Python pins, 17 npm pins and 23 Make targets validated. |
| Private structured-data/link/source check | Exit 0 | 2.820 s | Scoped JSON synchronization and source guards; 108 new Markdown/HTML links resolved in the initial integrated draft. Later editorial additions require the final bounded check. |
| Pandoc GFM rendering — initial | Exit 0 | 0.415 s | Local structural preview with existing embedded images. |
| Private README layout inspection — initial | Exit 1 | 0.565 s | Preview helper compared raw title whitespace; no application defect or changed test. Original assertion retained. |
| Pandoc GFM rendering — final presentation | Exit 0 | 0.525 s | Uses page-title metadata without a duplicated visible title. |
| Private README layout inspection — recovery | Exit 0 | 0.615 s | 1440/768/390-pixel layouts, three decoded images, paired desktop captures, no external requests or page overflow. |

The preview uses installed Pandoc and Playwright against a local static document,
with page JavaScript disabled and network requests denied. It is a structural GFM
rendering, not a claim of exact GitHub stylesheet equivalence or a new application
browser matrix. The desktop/mobile renderings were visually inspected; all three
viewport layouts were checked. No dependency was installed.

The private delivery handoff is the record for final committed-source checks,
delivery SHA, normal push and clean synchronization. This document does not invent
its own future commit identifier or unexecuted results.

**NOT RUN in this task:** application tests, full Python/integration/browser suites,
admission experiments, full coverage, paired Web builds, container builds/recovery,
security campaigns, `make validate`, CI or provider requests. No executable file
changed, so no application regression run was required by the authorized scope.

## Preserved limitations and decisions

| Scope | Current disposition |
| --- | --- |
| LOCAL/DEMO milestone | Owner accepted; implementation complete and architecture baseline frozen |
| Original admission p95 / whole-Web byte equality | Historical FAIL retained; no threshold or protocol change |
| Historical secret scanners | Nonzero exits retained separately from independently reviewed nonsecret classifications |
| Framework/dependency advisory | Documented, unresolved; no upgrade or security-immunity claim |
| Five deep routes / offline fallback | No fresh dedicated journeys for five patterns; immutable public fallback remains fixed dark |
| Complete Phase 3 qualification | Not rerun; prior failures and unexecuted gates retain their disposition |
| Checkpoint B / formal acceptance | INCOMPLETE; 30 rows and 48 scenarios pending, zero accepted |
| P3-10 / GitHub Actions | Unstarted / disabled and unverified |
| Real providers, Live, production, hosted registration | Separate external prerequisites and owner authorization required |
| Redis and retained resources | Two unclassified keys, original databases/volumes/images/environments and evidence preserved; no cleanup performed |
| Semantic reproducibility/scanner proposals | [Proposed only](../verification/LOCAL_DEMO_CONTRACT_PROPOSALS_20261117.md); acceptance does not approve them |
| License visibility / redistribution | [Wording proposal](../verification/LICENSE-VISIBILITY-WORDING-PROPOSAL.md) pending; `LICENSE.md` unchanged; dependency/binary/container rights unresolved |

The public GitHub metadata was read to confirm public visibility. The license's
“private and proprietary” wording remains an explicitly documented presentation
inconsistency pending owner approval of the existing minimal proposal. Source
visibility does not authorize reuse, provider-data redistribution or binary/image
publication.

## Complete changed-file inventory

All paths below are documentation or scoped status data. Application, tests,
migrations, lockfiles, generated contracts, broker allowlist, workflows and license
are byte-identical to the accepted snapshot. No resource cleanup or deployment
was performed.

- `CHANGELOG.md`
- `PROJECT_PROGRESS.json`
- `PROJECT_STATUS.json`
- `PROJECT_STATUS.md`
- `README.md`
- `VALIDATION_REPORT.md`
- `docs/DESIGN_FREEZE_LOCAL_DEMO_20261117.md`
- `docs/DESIGN_INDEX.md`
- `docs/DOCUMENT_GOVERNANCE.md`
- `docs/SYSTEM_ARCHITECTURE.md`
- `docs/design/UI_IMPLEMENTATION_ROADMAP.md`
- `docs/design/UI_REDESIGN_CODEX_PROMPT.md`
- `docs/design/UI_UX_DESIGN_SPECIFICATION.md`
- `docs/engineering/PHASE_3_TEST_STRATEGY.md`
- `docs/implementation/LOCAL_DEMO_ACCEPTANCE_20261117.md`
- `docs/implementation/LOCAL_DEMO_CONSOLIDATION_20261117.md`
- `docs/implementation/LOCAL_DEMO_IMPLEMENTATION_20261117.md`
- `docs/implementation/LOCAL_DEMO_ROUTE_COVERAGE_20261117.md`
- `docs/implementation/LOCAL_DEMO_SCOPE_20261117.md`
- `docs/implementation/LOCAL_DEMO_TRACEABILITY_20261117.md`
- `docs/implementation/PHASE_3_ACCEPTANCE_MATRIX.md`
- `docs/implementation/PHASE_3_SCENARIO_EVIDENCE.md`
- `docs/implementation/PHASE_3_TECHNICAL_BASELINE.md`
- `docs/implementation/evidence/local-demo-owner-acceptance-20261117.json`
- `docs/operations/LOCAL_AND_DEPLOYMENT.md`
- `docs/operations/PHASE_3_OPERATIONS.md`
- `docs/verification/LOCAL_DEMO_CONTRACT_PROPOSALS_20261117.md`
