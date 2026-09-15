# ADR-0028: Bounded scenario public pages

- Status: Accepted
- Date: 2026-09-15
- Scope: P3-02 scenario result and comparison views
- Related: ADR-0025; Phase 3 API service contracts; Phase 3 MCP tool registry

## Context

A canonical scenario retains up to 10,000 terminal components and original source
proof. Its private 32 MiB storage bound exceeds the 2 MiB public response bound.
Public views therefore need bounded traversal without losing financial rows or
misrepresenting a source preview as the complete saved result.

## Decision

Keep the frozen GetScenarioRun and CompareScenarios operations. Add optional
component_limit (default 25, range 1..100) and component_cursor (maximum 2048 chars).
Creation/cancellation return operational run metadata; successful detail reads
return the common summary plus one bounded component page. Scenario lists remain
metadata pages. The comparison request keeps exactly two distinct ordered run IDs.

Public pages contain original root/path identities, available instrument/entity and
classification/currency facts, unmodified financial values/ratios/quality/confidence,
winning/excluded/uncertain rule identities, and at most 128 sensitivity-use financial
rows. Public sensitivity use retains version/observation/driver identity, coefficient,
shock, effect and reason. It does not expand candidate observation arrays or full
source evidence into every public row. Source/proof identities can be sampled up to 16
per collection with an explicit omitted count; selected observation membership must
remain visible. Diagnostics can be sampled with explicit omissions. All financial
components remain traversable; no financial row may be silently truncated. Original
full proof remains in canonical storage and authorized reports. Public representations
must have distinct types/digests and never pretend to be the complete private result.

Construct each public page against a conservative 1 MiB canonical-byte subbudget,
including common summary/definition/context metadata. Stop before the next whole
component exceeds the budget, return a next cursor and retain requested page size
as a maximum. Never split a financial component. If even one compact component and
common context cannot fit, fail explicitly before any successful response. The final
transport also bounds its complete encoded envelope to 2 MiB. UTF-8 byte counts matter.

Reuse the existing signed CursorCodec with closed resource names and bindings to
the authenticated stable issuer and subject identity, account, ordered run IDs, saved result digests,
view version, limit and expiry no later than all selected run lifetimes. Authentication,
current grants and pinned/current source rights precede cursor parsing, decode and
conditional responses. Paginate immutable canonical component order with an integer
ordinal, avoiding a new mutable collection snapshot for already immutable results.
An expired or deleted source denies continuation without exposing financial payload.

Comparisons preserve each incompatible side and mismatch diagnostics, with no deltas.
A page traverses the bounded union of original root/path keys. No calculation is
rerun from current portfolio/provider values. Existing legacy MCP tools and schemas
retain their exact bytes; only the frozen new scenario tools acquire these new
optional page parameters before their first implementation.

Authentication and current server-side grants are validated on every request; a
cursor is not authority. A bearer token, token byte digest or refresh-session ID
is never a cursor identity input. Token refresh retains valid continuation only
when issuer, subject, owner, account and all pinned view inputs still agree.

This decision adds no operation or tool. The existing scenario operation names
and routes remain frozen. The optional page fields are additive before those new
interfaces are first implemented. Existing delivered API/MCP descriptors remain
byte-equivalent. Public encoding uses the existing canonical Decimal string
policy, and the final route envelope is measured independently from the public
page subbudget. No source evidence is silently presented as complete when omitted.

Validation requires byte-boundary and multi-byte text cases; whole-row traversal;
signed cursor tamper, expiry, changed identity/account/limit/digest cases; token
refresh continuity; authorization before cursor parsing and private decode; and
preserved incompatible comparison sides. Actual execution evidence belongs to
the implementing component, not this design decision.
