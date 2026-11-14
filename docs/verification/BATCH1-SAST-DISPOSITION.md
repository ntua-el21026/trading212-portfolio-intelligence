# Batch 1 extended SAST disposition

The changed-source scan `batch1-scoped-sast-01` used the unchanged seven repository
rules and retained pinned Semgrep image, offline and read-only. Its exact command,
source and receipt hashes are in the [command index](../implementation/evidence/phase-3-batch1-20261114.json).
The scan **exited 1 with eight blocking findings** across 43 scanned targets.
Ten files matched ignore patterns and one large file was skipped. This is neither
a complete repository scan nor a whole-SAST pass.

All eight matches are in migration `0035`, outside the Makefile's configured
`apps packages scripts` target roots. No reported finding is in those roots.
The migration was included as additional review scope. No scanner rule, ignore
file, test assertion or security gate was changed to obtain a pass.

Two implementation reviewers traced every interpolation to fixed source tuples.
The syntactic `formatted-sql-execution` rule matches DDL identifiers here; bound
value parameters cannot substitute SQL identifiers. The reviewed migration SHA-256
is `790f4bcb75eff2e8d5bf730f546a8aa33ea87998b50cf30610fb25ae869a8c35`.

| Finding line | Closed source of interpolated identifiers |
| --- | --- |
| 248 | Three research dependency/member tables, literal tuple at 243–247 |
| 255 | Three source/event/note payload tables, literal tuple at 254 |
| 259 | Three retention tables, literal tuple at 258 |
| 263 | Two literal X-ray table/kind pairs at 262; kind is `input` or `run` |
| 290 | Three dependency/member tables, literal tuple at 285–289 |
| 300 | Six payload/retention tables, literal tuple at 292–299 |
| 302 | Two X-ray tables, literal tuple at 301 |
| 313 | Eight exact helper signatures, literal tuple at 303–311 |

No request, environment, configuration, provider or database value reaches these
strings. Downgrade takes locks and refuses any feature provenance before changing
the schema, restores prior guard functions in place and uses no `CASCADE`.
The forward SQL definitions match those executed in the fifteen new PostgreSQL
component cases. The empty round trip and populated refusal have separate passes.

Disposition: eight reviewed false positives for SQL injection in this source;
no interpolation-related integrity defect was found. The original failed scan
remains visible. This review does not accept Phase 3, approve a policy exception,
claim independent owner verification or change future scanner coverage.
