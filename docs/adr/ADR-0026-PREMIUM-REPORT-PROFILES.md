# ADR-0026: Explicit document profiles on shared premium report routes

**Status:** Accepted implementation decision, 2026-09-15

**Authority:** The owner requires preserved existing contracts, explicit versions for
new semantics, complete canonical premium reports and shared execution resources.
This decision amends ADR-0024's one-to-one mapping between premium HTTP V2 and its
initial risk-only document schema. It does not alter the six legacy V1 report routes
or the original 25 MCP descriptors.

## Problem

The risk-only premium document/context schema `2.0.0` and profile
`report_sections_v2` contain closed risk family/table literals and require a risk pin.
Adding scenario semantics in place changes those schemas. Adding another six HTTP
routes for each premium family unnecessarily duplicates transport registration while
the renderer, storage, authorization, worker and cleanup are shared.

## Decision

Keep the existing six `/api/v2` premium report routes and their operation IDs. Add an
explicit bounded `profile` query selector. Omission selects exactly
`report_sections_v2`; its request defaults, risk-only schemas, canonical selection,
idempotency framing, stored bytes, collection semantics and renderer output remain
unchanged. V1 remains untouched.

Introduce one `report_sections_v3` outer format with canonical document/context
schema `3.0.0` for the remaining frozen premium families: risk, scenario, projection,
goal and research. Families/sections are closed literals; source bindings are typed,
bounded variants tied to actual canonical input kinds. Preserve existing profile2
classes and codecs; expose an honest versioned union only on the premium route
boundary. Unknown profiles, duplicate selectors and query/body profile mismatches
fail closed. Do not infer a new profile from unknown request fields.

Declaring the outer family vocabulary is not runtime support. Only implemented,
reviewed sections and binding variants pass validation. Reject a selected unsupported
section before capture, quota reservation or job insertion; do not create a placeholder
context, successful empty table or handler that does nothing. An explicit profile3
request can use the implemented risk section without migrating default profile2
requests or stored documents. New families use this same outer profile as they become
complete; a separate document-profile migration per implementation package is not
required.

The premium OpenAPI operation schemas will expand, so this is not exact descriptor
preservation of those new premium operations. The preserved behavior is their default
profile2 contract and bytes. Original25 MCP descriptors still reference V1 only and
must retain exact independent baseline fingerprints.

Scenario documents pin an owned succeeded immutable scenario run and use fixed
versioned scenario tables with full canonical component values, mappings, unavailable
reasons and source proof. They must not manufacture a risk pin, assign scenario proof
to the risk family or accept raw financial JSON. Projection/goal inputs bind retained
projection results and their actual pinned goal analysis. Research binds its retained
X-ray/source-event/note revision evidence; it does not invent a research_run_id. Exact
binding fields come from each implemented canonical contract and remain closed.
This ADR does not introduce an unrequested multi-run report API or silently relax
compatible-basis checks. The separately frozen two-run scenario comparison is not
permission to mix incompatible currencies or snapshots in a report with one declared
monetary basis.

Keep actual table key enums closed. Each newly implemented family's reviewed fixed
schemas add explicit enum members and typed binding variants as needed. Table keys
carry their semantic version and descriptors retain their schema digest. No arbitrary,
opaque or pattern-only table name is accepted in place of the closed registry. This
ADR permits this additive registry/variant evolution within profile3: its generated
union/OpenAPI descriptor truthfully changes when a new family becomes supported,
while the outer document layout/profile remains3. An existing table's financial or
column semantics change only through a new table version/key; no redefinition under
an existing key. Do not use a family addition to change numeric methods.

Every registry addition must preserve all previously emitted profile3 selection,
document/context and artifact bytes and request digests. Existing optional-field
omission/defaults and canonical ordering remain exact; do not serialize a new null
selector into old documents or reinterpret old bindings. New binding variants must
not introduce required fields into old variants. A change to the outer structure or
existing semantic meaning beyond these declared additive variants requires a new
explicit document-profile version and decision.

Persist normalized document-contract/profile metadata and validate it against the
selection, header and contexts before decoding or execution. The smallest schema
change may extend existing `contract_version` to3, documenting that it identifies the
document contract while `/api/v2` identifies the premium transport. Do not rewrite
existing contract2 bytes or change old semantic command identities. New profile
requests have explicit new framing; all profiles reuse the existing report outbox
task, engine, worker and renderer version unless the actual rendering method changes.

Default lists select profile2 at SQL collection materialization, count and cursor
creation. Explicit profile3 lists have a distinct profile-bound collection/filter
identity and cannot produce mixed pages. Keep existing profile2 cursor identities
unchanged. Direct status, manifest, grant and content operations require the selected
profile to match authorized normalized metadata before private payloads, ETags/304,
idempotent replay or grant/content processing. Wrong-profile direct IDs return safe
not-found. Profile is part of new semantic routing identities; a grant cannot cross
the document boundary. Current owner/account/source authorization remains first.

Normalize a typed dependency for each selected retained premium run. Dispatch current
authorization, digest/completeness checks and physical retention by a closed family
and profile. Every copied source requires current/pinned STORE, DISPLAY and REPORT;
EXPORT applies only to an export contract. Clamp expiry to all upstream/current
deadlines and purge dependent report copies before a selected source physically
completes, using the existing shared budgets and lock order.

Reuse unchanged scalar/cell/source/renderer contracts. Closed family declarations,
currently supported section validation and the actual reviewed table registry are
separate: reserve the frozen family vocabulary, but never advertise an unfinished
section as operational or substitute an empty success. Future implementation may
need its own normalized data-table migration; it does not need a new report contract
version merely to add an authorized profile3 family.

## Acceptance

Prove unchanged V1 descriptors and report bytes, unchanged default profile2 risk
bytes and request digests, preservation of earlier profile3 fixtures after every
registry addition, profile-scoped SQL lists/counts/cursors, unsupported-section and
profile mismatch denial before mutation/decoding/replay/download, complete scenario
report parity and all four formats within existing limits. Retain 32 MiB document,
2 MiB manifest, 256 licenses,
100,000 rows per table, 1,000 PDF pages, 10 MiB per artifact and 25 MiB total artifacts.
An over-bound complete proof fails safely; no truncation or bound increase is part of
this decision. No additional service, container or provider capability is introduced.
