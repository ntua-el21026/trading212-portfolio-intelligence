# ADR-0034: Bounded account aggregation and distinct synthetic custody ingestion

**Status:** Accepted design; implementation and runtime evidence pending.

Keep the frozen six aggregation operations and four paths. A selection pins one
ordered tuple of 1..8 distinct owned account/snapshot pairs, reporting currency,
source cutoff, and `canonical_instrument_v1` identity policy. Snapshot values and
canonical listing-to-instrument identity are authoritative. Never join by ticker,
rewrite a broker activity record, select a latest snapshot, or invent performance.

Run creation is a bounded synchronous transaction using the existing premium
single-execution advisory slot. Check the existing global running-job state and
owner admission before capture. Reserve32MiB within the shared256MiB owner cap;
charge actual canonical and normalized copies before atomic publication. Selections,
including tombstones, consume the existing512 definition-version budget. This adds
no fourth durable task, queue, scheduler or container. Busy admission returns429.
If-Match advances only the selection operational revision. The immutable content
and original idempotent receipt remain stable. All member grants are current on
first execution and idempotent replay.

The20-second wall ceiling includes capture, decoding, calculation, serialization,
normalized publication and final authorization. Check remaining time around byte
operations and loops and bound SQL by remaining deadline. It is a cancellation
ceiling, not an exemption from the accepted measured read/write p95 SLOs. An actual
latency miss requires optimization or an explicit design amendment. No partial
transaction/result becomes success. Complete input plus all result/proof copies
are additionally bounded by one combined32MiB limit for this synchronous family.

A request may pin at most256 exact FX-observation IDs, keyed by actual account and
source currency:32 currencies times8 accounts. Resolve their original owned FX
snapshot and validate source/target direction, effective time, first-known cutoff,
original/current licence and acquisition rights. No caller rate or inferred route
is accepted. Missing binding preserves native partial values and makes the full
total unavailable; a supplied foreign/mismatched/duplicate binding is invalid.
Use `premium_decimal96_q18_v1`. Convert each complete component once to Q18, sum
those published components exactly, and disclose the signed difference between
that sum and Q18 of the unrounded complete sum. Grouping/account subtotals never
introduce an extra rounding boundary. Unknown values never contribute fabricated0.

Optional activity_window is bounded to3,660days and10,000 immutable retained source
candidates across all accounts, within the same byte ceiling. Omission reads no
activity and returns not_requested coverage. Preserve complete source revision and
coverage proof. Deduplication is per broker/account/external record identity;
actual holdings in different accounts add. A unique internal transfer requires
mutual retained counterparty references, stable transfer identity and opposite
principal. Cross-currency matching additionally requires exact retained FX and fee
proof. Equal dates/values do not suffice. Unmatched/ambiguous legacy rows remain
explicitly degraded; current holdings availability remains independent.

GetAggregateRun selects one closed view: holdings(default), components, accounts,
or transfers; pages default25/max100, cursor2048, complete envelope2MiB. Holdings
and activity use separate canonical payloads and source memberships. Every view
reauthorizes every selected member before cursor/304/decode and before return;
transfers also requires current activity:read. A cursor binds owner, principal,
selection/run/digest, view, limit and authorization/collection identity. Changing
view cannot disclose an activity payload. No whole financial row is truncated.

Source copies use the existing bounded physical cleanup composition: direct indexed
retained memberships block original sources until run and dependent report copies
are gone. Reserve every probe, target and trigger/counter inspection within the
shared4,096-row/64MiB/512batch budget. Metadata markers and immutable audit/tombstones
survive, retained charges decrease only on actual payload deletion, and busy-owner
cleanup resumes. Extend the existing purge_owner_scenario_payloads composition
with an aggregation participant; inactive-owner authorization is not a new public
owner-erasure API. No graph traversal or unbounded historical prefix is hidden in
SQL guards.

A second `SyntheticCustodyIngestionProvider` accepts a distinct closed native
fixture contract, namespaces provider record/schema IDs, and adapts it to the
existing BrokerAccountDataProvider/ingestion/materializer envelope. The public
provider enum remains trading212|synthetic. Shared canonical ISIN identity joins
economic instruments while separate native listing/account provenance is retained.
Only the exact native schema may attest its extra transfer proof; it does not mark
broker records internally matched. Test actual PostgreSQL canonical parity and
repeat-ingestion idempotency against the first adapter. The original ten Trading212
GET capabilities remain sealed. This is an explicitly synthetic adapter, with no
claim of real second-broker credentials, network integration or paid entitlement.

PostgreSQL18 transaction-local `transaction_timeout` bounds the complete database
transaction, alongside the client monotonic fence and statement timeout. It may
terminate a timed-out connection; discard that connection through the normal
SQLAlchemy error path. No server-wide setting changes. See the official
[PostgreSQL18 timeout contract](https://www.postgresql.org/docs/18/runtime-config-client.html#GUC-TRANSACTION-TIMEOUT).
