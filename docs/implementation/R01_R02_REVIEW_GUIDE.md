# R-01/R-02 candidate review guide

## Owner-authorized progression, 2026-09-14

Phase 2 is **accepted by the owner for progression** to Phase 3. The accepted
corrected source is `f88b0199b2d8691ff89101b7991e9bb0fea1d1ca`, tree
`5ac0dba52e369a30a32a2d7d5b41409e12fc0911`; its observed delivery and this
assignment's clean starting main are `d2ebdaf96d1b61aacea5c6492824946540f88803`.
The owner-reported independent code review found R-01/R-02 corrected and no new
blocker within its inspected scope. It did not independently inspect the full
local archives or rerun every gate. This decision is progression authority,
not independent full-release verification.

Phase 3 is in progress toward `1.0.0`. Its implementation and final local
validation remain pending; independent review will remain pending for the new
candidate. GitHub Actions is `deferred_by_owner`, unverified. Production
release/deployment, paid-provider purchases and Live are not authorized.

See the [retained owner decision](evidence/phase-3-owner-authorization-20260914.json). The observations below are the
historical delivery record. Their then-pending acceptance and not-started Phase 3
statements retain their original temporal meaning; the owner decision above is
the current progression authority. Historical test/artifact bytes are unchanged.

## Historical record before owner progression

The corrected implementation is `f88b0199b2d8691ff89101b7991e9bb0fea1d1ca`,
tree `5ac0dba52e369a30a32a2d7d5b41409e12fc0911`, following
`6479186f378bab5ab6fcfd9b29fd444eebd28e6b`. Local validation passed; independent
acceptance remains pending. GitHub Actions is owner-deferred/unverified and
Phase 3 remains `not_started`. See the [current machine summary](evidence/phase-2-r01-r02-f88b019.json)
and [validation report](../../VALIDATION_REPORT.md).

## Retrieve and inspect

The portable copy is at
`C:/Users/peppa/.codex/artifacts/trading212/review-f88b019`.
The original retained records are beneath
`/home/peppasmich/.local/state/t212pi/20260908-resume/r01-r02-20260913`.
These are local artifacts, not a public download. Share the portable directory
with an authorized reviewer; bulk records are deliberately outside Git.

- `root-review.json`: source/tree, actual gate commands/exits/timestamps, counts,
  coverage, archive hash and pending-review/deferred-CI boundaries.
- `supporting-records.zip`: 2,400,461 bytes; SHA256
  `3b199c5863f93ff02c804cefc20c7f93b1604c7f3495a25321655e2114e94699`.
  Contains actual full/focused/failed gate logs, browser records, source/image
  scans, runtime observations, coverage JSON, inventories and inspectable helper
  source copies. `manifest.json` maps original absolute paths to relative ZIP
  members; absolute original paths inside records are provenance, not missing
  substitutes for their portable copies. `counts.json` preserves session overlap.
- `capture-coverage-supplement-f88b019-01.zip`: 26,789,930 bytes; SHA256
  `5ffa075e55cb74ed79bdd57c8062cb01fb7331881c1e6e74b93372f50ff7162d`.
  Contains all 70 required PNG captures and the full-run `coverage.sqlite`.
  The adjacent JSON records member/original hashes and actual archive canary
  results. Images are available for review; no visual approval is inferred.
- `portable-pack-scan-f88b019-02.json` and `postassembly/`: actual final package
  scan plus the original failed scan, scoped filename classification, scanner
  source/proof, and later documentation-delivery/cleanup receipts. This avoids
  inserting postassembly evidence into the archive it hashes.
- `windows-pack-copy-01.json` binds the initial byte-identical Windows copies;
  later sidecars have separate copy hashes. `DELIVERY.json` records the actual
  later documentation SHA and executable-equivalence check after pushing.

To inspect without expanding bulk logs, use a ZIP viewer or Python's standard
library. For example, from the portable directory:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath .\supporting-records.zip
Get-FileHash -Algorithm SHA256 -LiteralPath .\capture-coverage-supplement-f88b019-01.zip
```

Compare the complete hashes above. Open `manifest.json`, locate a record by
`original_path`, and open its `path` inside the ZIP. The 19,243,999-byte full log
is retained verbatim. Recorded commands and pinned helper copies establish what
ran; preparation-only comments are not execution or acceptance evidence.

## Identity and regression contract

The [authentication identity contract](../security/AUTHENTICATION_IDENTITY.md)
was documented before production changes. External issuer/subject values retain
case, slashes and punctuation exactly, with bounded StringOrURI validation;
internal principal/owner IDs keep their strict grammar. URI acceptance never
permits fetching. Trusted configured key/issuer/audience and supported asymmetric
algorithms remain fixed. MCP requires its HTTP(S) issuer profile while preserving
the exact value in discovery and reconstructed principals.

An explicit `principal_id` remains the trusted internal mapping. Only an absent
claim can fall back to a subject that already satisfies the internal-ID grammar;
explicit null/empty values are rejected. An external subject never creates an
owner mapping. NumericDate claims are finite numbers, excluding booleans and
strings, bounded to representable UTC timestamps. Fractional values retain
microsecond precision; malformed claims produce sanitized authentication errors.

The immutable full log contains 9 real signed identity, 309 claim-boundary,
3 API, 16 metadata, 46 actual MCP/PostgreSQL transport and 40 current-status
contract cases. RS256, ES256 and EdDSA use ephemeral synthetic signing material.
The baseline RED logs and selected drivers demonstrate the original JWT/API
failure; the later MCP baseline overlay is explicitly retrospective component
comparison. It is not a whole-baseline immutable run. All development failures
and corrected test assumptions retain their original outcome and source scope.

The Phase 2 crosswalk resolves all 156 unique selectors in the preserved 79-entry
ledger. The Stage A/Phase 1 crosswalk binds original scenario selectors to actual
passed full-run cases. They show execution consistency, not independent acceptance.
The same-source seven-service runtime records include nonempty retained state,
refresh/alert Redis-loss recovery, replay behavior, API/MCP/web parity and teardown.

## Evidence limitations

The collector corrected Playwright's `beforeAll` clock semantics using pinned
1.62.1 source. Sixty web timing checks remain unchanged; ten widget captures are
bounded by their own recorded start and the next test start on the same worker.
No wall-clock completion or hook duration is invented, and no PNG mtime changed.
The first portable scan failed because a broad secret regex matched a substring
in a Next.js module filename. The corrected scan classifies exactly two path
metadata occurrences in one hash-bound canary member; generic token, private-key
and export-URL checks remain. Original pack bytes and failed records are retained.
Trivy passes preserve configured HIGH/CRITICAL and ignore-unfixed filtering;
scanner passes are not universal vulnerability/privacy guarantees.

Real Trading 212 Demo/history and opening coverage remain external; optional Live
is disabled and untested. Production host/domain/IdP/secret manager, public
HTTPS/OAuth MCP/ChatGPT registration, licensed data, notification destinations,
and production storage/backup restoration remain unverified external gates.
Synthetic local JWT verification is complete and is not one of those blockers.
The main ruleset recommendation remains nonblocking/not configured; no repository
administration was changed. The pinned MCP SDK remains 2.1.1.

The delivery commit changes only the ten named status/report documents plus this
guide and the individually named summary JSON. Its own contents leave delivery
SHA null; `DELIVERY.json` proves the actual parent, normal push and content/type/mode
equivalence for every other tracked file. This is not a second full run at the
documentation commit. Historical Stage A/Phase 1/Phase 2 evidence is preserved.
