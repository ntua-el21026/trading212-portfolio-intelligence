# Phase 3 Implementation Report

**Current:** P3-01 canonical calculation, normalized storage and bounded worker implemented; interface/retention work in progress
**Target:** 1.0.0; independent review pending; production not authorized

Start main d2ebdaf96d1b61aacea5c6492824946540f88803. Governance delivery
30fe2ede666bff35e3e95173abcf34558a729cc1 records owner acceptance for progression
without modifying historical artifact claims. Immutable governance gate passed:
463 targeted tests, strict mypy 605 files, Ruff/repository/workspace/broker/architecture/
secret checks and affected Prettier. Scope is governance, not Phase3 runtime completion.

Design inventory: ten packages,30 local acceptance rows,48 mandatory scenarios.
No package/row/scenario is locally complete at this boundary. Implementation, scenario
execution, full candidate validation and independent acceptance remain separate.
Governance logs/JUnit/commands/source identities reside in the external phase3-20260914
evidence directory; add package evidence only after actual executions.

GitHub Actions deferred_by_owner/unverified. No production/public release, Live,
paid-provider access or public ChatGPT registration has been performed.

## P3-01 numerical foundation

Implemented strict definition/series contracts, isolated Decimal96 arithmetic, PSD/
correlation/shrinkage, modeled Euler contributions, historical/lognormal tails and
complete-case observed/benchmark/rolling estimates. Focused numerical/contract tests
passed (54 tests). Independent references use rational covariance and a different
200-digit positive-series normal integral with Machin pi. This is partial package
implementation at d6bb100: canonical history capture, durable persistence/jobs and
interface delivery remained pending at that numerical foundation boundary. No acceptance row/scenario or package is marked complete.


## P3-01 canonical history and complete calculation object

Added a retained-history builder using canonical TWR at actual captured reporting
session closes, explicit complete month ends, canonical flow anchors, total-return
benchmark/asset sources, FX selections, source cutoff and original drawdown. Raw or
split-adjusted asset prices remain explicitly incompatible with a total-return risk
series; the existing accounting engine still handles supported portfolio actions.
The builder preserves canonical missing reasons and applies a combined preflight
cell bound before valuation. No caller return array enters a service contract.

The immutable calculation now carries observed statistics, the original and explicit
regularized covariance, correlation, historical/lognormal tails, and a distinct
current-weight model. It binds scope/cutoff/snapshot/X-ray digest and the separate
current valuation date. Incomplete selected material exposure, including cash without
an explicit return series, cannot publish full modeled risk. Exact current value
ratios are used before Q18 publication; weight and Euler display residuals are
reported without allocating them. Concentration reuses X-ray issuer partitions and
its exact coefficient ratio for effective holdings, preserving unknown mass/quality.
A fixed-schema private codec verifies the canonical result digest before replay.

Focused execution passed 85 tests across numerical, statistical, history and complete
result modules. Independent references include Fraction covariance, Decimal160 risk,
known direct/indirect issuer partitions and equal-third rounding. A fixture initially
had mismatched X-ray dependency account IDs; correcting its scope made the integrated
case pass. No production boundary was relaxed. Original attempt logs are retained.
These are working-source component checks; durable normalized storage/jobs, current
read/execute/export authorization, REST/generated clients/web/MCP/report integration
and full package acceptance remain pending. The acceptance counts stay at zero.


## P3-01 normalized storage and bounded worker

Migration 0017 extends the existing application command identities and current
principal grants, adds 17 normalized premium/risk tables, and extends the existing
immutable collection snapshots for risk definitions, versions and run metadata.
Calendar references retain the canonical source key/version; persistence resolves
that pair to an owned immutable calendar UUID. Existing Phase 2 financial methods,
report commands and source identities keep their contracts.

Risk definitions have immutable predecessors, revision checks, semantic idempotency,
transactional audit and current-grant checks before replay/cursors. Risk admission
pins owned history, portfolio, optional X-ray and ordered asset mappings. Current
source display/store rights are checked before private decode, and the shortest
applicable source lifetime bounds the run. The same valuation-cell preflight runs
at admission and calculation; combined private input bytes are bounded to 32 MiB.

Runs reserve capacity in PostgreSQL: at most two active jobs per owner, one running
premium job globally, 512 definition versions and 256 MiB retained/reserved payload.
Publication verifies the canonical digest and every fixed normalized projection.
The canonical historical drawdown can retain its partial-value reason. Normalized
storage size is included when releasing the conservative result reservation.

The fixed risk outbox is relayed by the existing dispatcher. Messages carry only
opaque identities and the input digest. Publication claims, consumer leases,
heartbeats, absolute per-attempt deadlines, retry bounds and immutable attempts
fence stale or cancelled workers. Current initiating identity/grants and source
rights are checked again at load/publication. The existing Celery worker starts
one isolated calculation subprocess with a 240-second attempt deadline, 512 MiB
address-space limit, minimal environment, fixed codecs and Linux parent-death kill.
Cancellation/deadline tests verify that the child is killed/reaped without retaining
scratch files. No additional Compose service is introduced.

Working-source component checks passed 44 migration/schema/definition/run/job tests
and 8 process/message tests. They include an actual child publishing through the
fenced PostgreSQL store. Original failed attempts remain retained: a calendar key
was initially mistaken for its storage UUID, and a dispatcher claim initially
failed to clear its dispatcher identity. Both contracts were preserved while fixing
the implementation. These counts are not final candidate validation.

A populated 0016-to-0017 upgrade passed: all 212 legacy tables retained identical
row counts and hashes of every pre-upgrade column, and canonical historical replay
was unchanged after introducing the 17 new tables. A separate real source-rights
test confirmed that current store revocation and a tightened retention limit deny
risk access before private decode, including idempotent replay and worker loading.
This migration proof is not a backup/restore exercise.

REST/generated clients, web/MCP/report integration, shared physical source-retention
hooks, broader adversarial/performance evidence and full P3-01 acceptance remain
pending. The other Phase 3 packages remain pending. No acceptance row/scenario or
package is marked complete, and no public premium MCP tool is registered yet.
