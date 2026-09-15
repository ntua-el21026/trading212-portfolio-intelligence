# ADR-0031: Scoped research items and bounded retained provenance

**Status:** Accepted design; runtime integration and acceptance remain pending.

The eight accepted research operations keep their existing paths and meanings. Add
an explicit item_id UUID to ResearchItemView: a discoverable saved item binds one
owned account, one immutable event revision and digest, one actual saved X-ray run
and complete pin digest, and one selected source cutoff. Direct reads reauthorize
these exact records and never substitute a latest result or source. The item stores
identity metadata only; its deterministic portfolio facts are copied from the same
retained authorized X-ray result on read, with no numerical recomputation or extra
financial payload copy.

Research event identities and semantic deduplication are scoped to account, making
ReviewResearchEvent.event_id resolve one authorized account without adding a caller
owner/account escape hatch. Original normalized licensed source/citation identities
remain reusable within the owner. Source corrections append an immutable revision;
new material alias citations append a revision retaining their union. Retrieval-only
changes retain their complete original witness metadata/citation memberships without
changing material revision/review identity. A later correction from a previously
grouped provider alias becomes a separate account-local canonical event with that
provider key as its primary identity. Its local revision starts at 1; an immutable
alias-promotion relation preserves the original group/alias and exact incoming
correction receipt, including the provider revision ancestry. The original event
and review remain unchanged. Subsequent receipts resolve to the promoted stream;
no citation is fabricated or carried into different source facts.
Current owner notes and exact reviews remain separate. Review state is shared by
the account owner across currently authorized principals, with the exact original
actor and command receipt preserved. Later material revisions are unreviewed. An account research-state
revision binds collection fingerprints; mutations invalidate old sorted/filter
cursors instead of silently changing their membership or review ordering.

Bound immutable source versions, material event revisions, and publication witness
receipts to 10,000 aggregate per owner,
and saved item headers to 10,000 per owner. Tombstones count toward these bounds.
Owner note revisions participate in the shared 512 definition-version ceiling.
Research licensed payload copies participate in the shared 256 MiB retained premium
capacity. Charge canonical bytes and all duplicated normalized source payload
fields, including text and publication metadata; the same
logical content copied twice incurs two charges. Neither retrieval, aliases, item
creation nor collection TTL renews original source retention. New same-fact versions
are clamped to the earliest retained original semantic source lifetime. Notes keep
only owner-authored prose and opaque citation pins; their owner content survives
provider payload expiry. Note revision identities/citation pins are separate from
purgeable canonical text and six normalized owner fields; explicit owner erasure
removes that text while retaining immutable audit identities. Expiry denies source
reads immediately and drains every
licensed copy with the existing bounded cleanup budget before completing markers.

Research publication is a private fixed typed adapter boundary. A typed capability
authority must authorize the exact owner/provider/entity/news-or-overview/license
and pinned capability grant on publication and every retained read. Missing authority
or rights is explicit denial. Existing price capabilities do not imply news rights.
This decision adds no provider fetch, public source registry, network endpoint,
credential, synthetic fallback, or model synthesis. The same optional typed authority
is injected into the existing source cleanup composition. Without it, reads deny
and cleanup may conservatively remove copied payloads without provider I/O. A single
metadata-only cleanup watermark rotates over retained source headers so a revoked
source is not indefinitely hidden behind a prefix of permitted sources. All actual
metadata reads, including delegated grant lookups, use the existing shared purge
budget. Normal operations use sources → xray → historical → premium → research
owner locks; cleanup skips busy owners and deletion triggers never wait while
holding a payload tuple. Actual provider entitlement
storage/wiring remains the separately authorized provider workstream.


## Bounded physical cleanup clarification

Research cleanup advances a durable global or exact-owner **raw source-header**
keyset. Completed, empty and currently live headers count toward the same 4,096
physical-row allowance; a SQL payload/marker predicate must not discard an
unbounded prefix outside that allowance. Exact-owner erasure resumes at a partial
source, while a global sweep can rotate past a busy owner and revisit it.

The existing event-citation witness additionally binds its actual source-version
identity and a trigger-owned `copy_pending` flag. A covering owner/source/pending/
revision index finds only remaining copies. Every flag starts true on independently
validated publication and becomes false only from the event payload's AFTER DELETE
trigger, after the whole retained copy disappears. Canonical citation bytes and
immutable provider/source identities do not change. The two operational metadata
columns add 16 UUID bytes and one boolean per existing bounded witness; they do not
copy provider prose or portfolio amounts, and survive as audit metadata. There are
at most 64 witnesses per event revision within the accepted owner revision cap.

The shared cleanup budget reserves SQL work before mutation: event deletion charges
384 rows for its target, at most 64 source-witness checks/flag transitions, exact
payload-absence guards and both capacity updates. Source/note deletion charges eight
rows. Payload bytes are reserved twice (size/charge inspections), while retained
capacity decreases only by the exact bytes actually removed. Cursor/marker mutations
and empty indexed probes receive conservative fixed charges. No ceiling is raised.


## Bounded page authority clarification

The private provider authority also supplies a fixed typed SQL eligibility predicate
for actual normalized owner/provider/entity/capability/licence/original-grant scope,
current/pinned uses and clocks. It is authoritative provider entitlement logic, not
maintenance-cache permission. It accepts no raw SQL, table/column name, source array
or public query operation. Missing authority is false. P3-07 must implement this seam
against real normalized approvals; fixture implementations are explicitly synthetic.

Each page-sized returned source set receives an independent exhaustive batch grant
check before private source decoding and again before return. The batch method uses
at most one bounded metadata statement, returns one exact ordered grant per source,
and rejects missing/extra/cross-scope/expired/revoked bindings. The same eligibility
predicate is reapplied to the exact filtered count/rank at the final boundary.
Unauthorized events remain absent from both items and aggregate page counts.

Research page authorization joins current principal, account, grants and erasure
state in one statement with the existing ordered owner locks, and repeats the full
check before return. Mutable research epochs bind signed account/principal/filter/
run/cutoff cursors; any note/review/material-source mutation invalidates an old page.
The exact saved X-ray run/digests and normalized dependencies are checked by the
three-statement retained-X-ray reader without provider/history recalculation.

An aggregate fingerprint of the complete authorized immutable revision set also
binds each cursor. Grant changes that do not update the account epoch invalidate a
cursor when eligible membership changes. Final count/rank and source checks reject
an authority change during the current read.

Only one selected page of event metadata and its at most 64 citations per item are
materialized in Python; exact eligible count/rank use indexed server-side queries.
No page request hydrates or creates 10,000 candidate item headers. Only whole items
that fit the actual 2 MiB response get an atomic immutable identity. Note payloads and
citations are batched, preserve every normalized/canonical value, and resume after
the last whole revision that fits. Canonical profiles and financial strings do not
change. The maximum successful summary path is 12 SQL statements including initial/
final authority and locks, provenance reads, two real entitlement batch statements,
source/notes payloads and item admission. This is a query-budget design; actual
latency/RSS/SLO claims still require representative measurement.
