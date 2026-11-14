# Dependency and container remediation — 2026-11-13

This bounded stabilization retains the runtime majors, proprietary project license,
broker boundary and release metadata. Historical baseline pins and successful
receipts describe their original sources. This record describes the subsequent
security changes; it does not establish Phase 3 acceptance or production approval.

## Locked dependency changes

Fresh pip-audit 2.10.1 reported 64 advisory records across five packages in the
starting lock, including two more Pillow records than the cited CI run. Duplicate
advisory records are retained in the scanner evidence. The production pnpm audit
reported five high and three critical findings, plus lower-severity findings.

| Package | Previous | Selected | Reason and primary version metadata |
| --- | --- | --- | --- |
| MCP / mcp-types | 2.1.1 | 2.2.0 | First fixed release in the existing major; [MCP](https://pypi.org/pypi/mcp/2.2.0/json). |
| OpenTelemetry API / SDK | 1.44.0 | 1.45.2 | Initial step 1.45.1; follow-up trace-context fix and exact SDK pairing; [API](https://pypi.org/pypi/opentelemetry-api/1.45.2/json), [SDK](https://pypi.org/pypi/opentelemetry-sdk/1.45.2/json). |
| OpenTelemetry semantic conventions | 0.65b0 | 0.66b2 | Initial step 0.66b1; exact SDK 1.45.2 dependency from its release metadata. |
| PyJWT | 2.13.0 | 2.15.0 | 2.14.0 leaves reported findings; [metadata](https://pypi.org/pypi/PyJWT/2.15.0/json). |
| Pillow | 12.3.0 | 13.0.0 | Lowest reported fixed release; report rendering requires compatibility validation; [metadata](https://pypi.org/pypi/Pillow/13.0.0/json). |
| certifi | 2026.7.22 | 2026.10.18 | Trust-store security update; [metadata](https://pypi.org/pypi/certifi/2026.10.18/json). |
| Next.js and matching lint packages | 16.3.3 | 16.4.1 | Lowest release fixing all reported Next findings; [metadata](https://registry.npmjs.org/next/16.4.1). |
| sharp | 0.35.4 | 0.35.5 | Fixed native-library dependency; selected through Next's compatible optional range; [metadata](https://registry.npmjs.org/sharp/0.35.5). |
| source-map-js | 1.2.1 | 1.2.2 | Exact vulnerable-version override within PostCSS's existing range; [metadata](https://registry.npmjs.org/source-map-js/1.2.2). |
| Zod | 4.5.4 | 4.6.6 | Additional fresh audit finding; consistent web/client pins; [metadata](https://registry.npmjs.org/zod/4.6.6). |

The selected Python releases support Python 3.13. Next and sharp declare Node
`>=20.9.0`; Next accepts the existing React 19 versions. Pinned uv 0.12.7 and
pnpm 10.34.5 generate the locks. A lock resolution or clean dependency audit does
not establish application compatibility; focused and full runtime evidence is
recorded separately in the stabilization report.

## Trace-context follow-up observed on 14 November

The later dependency audit found `CVE-2026-126360` in the initial API/SDK 1.45.1
step. The [upstream advisory](https://github.com/open-telemetry/opentelemetry-python/security/advisories/GHSA-mf5v-w3w3-f6cg)
was published on 5 November; it rejects oversized trace-context input in 1.45.2.
Current exact pins are API/SDK 1.45.2 and semantic conventions 0.66b2. Earlier
1.45.1/0.66b1 receipts retain their original source and scanner scope.

Three benign public boundary cases produced two passes / one failure on 1.45.1.
After the patch, 279 focused security/observability cases and eight PostgreSQL
observability cases passed. A new initially absent HTTP cache and explicit
Python 3.13.15 / pip-audit 2.10.1 run reported zero findings or skips across
67 runtime dependencies. Existing caches and the project `.venv` were preserved.
These are source-bound checks; no exploit or performance result is claimed.
Full-target, actual rebuilt-image and startup qualification remain pending.

## Reproducible Debian security packages

The original image tags and digests remain pinned. The CI application builds
failed because `libpcre2-8-0=10.42-1+deb12u1` had disappeared from the moving
Bookworm repositories. The available security revision is `10.42-1+deb12u2`.
PostgreSQL and Redis also reported fixable APT, PCRE2, OpenSSL and zlib findings.

The two committed Deb822 files use immutable
[Debian](https://snapshot.debian.org/archive/debian/20261113T000000Z/)
and [Debian security](https://snapshot.debian.org/archive/debian-security/20261113T000000Z/)
snapshots. Archive-key signature verification is retained. Disabling
`Check-Valid-Until` permits reuse of intentionally frozen signed metadata; it
does not disable signature or package-checksum verification.

| Suite | Exact security pins |
| --- | --- |
| Bookworm application runtimes | CA certificates 20250419~deb12u2; APT/libapt 2.6.2; PCRE2 10.42-1+deb12u2; OpenSSL/libssl3 3.0.22-1~deb12u2; perl-base 5.36.0-7+deb12u4. |
| Trixie PostgreSQL/Redis runtimes | CA certificates 20250419+deb13u1; APT/libapt 3.0.4; PCRE2 10.46-1~deb13u3; OpenSSL libraries/provider 3.5.7-1~deb13u3; zlib 1:1.3.dfsg+really1.3.1-1+deb13u1. Existing exact gzip, Perl and SQLite pins remain. |

The CA updates revoke trust following the compromise described by Debian's
[Bookworm advisory](https://lists.debian.org/debian-lts-announce/2026/10/msg00039.html)
and [Trixie advisory](https://www.debian.org/security/2026/dsa-6572).
The selected security revisions are present in the frozen signed package indexes.
This correction applies to all six runtimes, including Python bases that already
contain an older trust store.

The pinned PostgreSQL, Redis and Node slim bases omit system CA roots. Their
HTTPS snapshot bootstrap copies only the public CA bundle from the existing
digest-pinned Python base, then installs the exact signed CA package. Redis also
omits OpenSSL's default trust paths; controlled probes demonstrate that specifying
the copied bundle through APT's
[CAInfo option](https://manpages.debian.org/trixie/apt/apt-transport-https.1.en.html)
resolves discovery while certificate and hostname verification remain enabled.
The web bootstrap uses the same explicit path. No private key is copied, and no
HTTP fallback or certificate-verification bypass is introduced.

Installation uses `--only-upgrade`, preserves the dpkg inventory and removes
runtime package-manager executables. The snapshot package indexes were inspected
before selection. Actual builds, runtime probes and scans remain separate gates.

## License disposition

Upgraded MCP, PyJWT, Next and Zod retain MIT licensing; OpenTelemetry and sharp's
JavaScript package retain Apache-2.0; Pillow uses MIT-CMU, certifi uses MPL-2.0,
and source-map-js uses BSD-3-Clause. Their own notices and terms remain applicable.

sharp's prebuilt libvips dependency includes LGPL-3.0-or-later components. The
existing Trivy license classification acceptance is retained for local validation
of unmodified binaries. It is not a vulnerability exclusion or authorization to
publish runtime images. A public source repository does not approve public binary
redistribution. Any such distribution requires a separate obligations review,
including retained notices, corresponding source and relinking requirements as
applicable. No production release or public image distribution is authorized.

An additional scan of the local working directory classified three existing
license texts in the ignored installed environment: psycopg and its binary wheel
as LGPL-3.0, and ReportLab's DarkGarden font notice as GPL-2.0. These files remain
intact. The CI filesystem job scans a clean source checkout before environment
installation; its scope is reproduced with a complete, hashed candidate source
export. The existing runtime image matrix scans vulnerabilities and secrets.
No license classification or vulnerability gate is weakened to reconcile these
different input scopes. Public binary obligations remain a separate review.

## Secret-scanner review

Pinned Gitleaks 8.30.1 reproduced 38 history findings. Each was independently
classified in [the exact-fingerprint review](SECRET_SCAN_REVIEW_20261113.json):
37 recomputed contract/client digests and one synthetic report row identifier.
Matched values were neither displayed nor retained in the review. The exceptions
bind only the original commit, path, rule and line. No credential was found among
these 38 results; this is not a comprehensive credential-free guarantee.

The default Gitleaks rules, existing narrow checksum policy, high-confidence
secret scan, vulnerability severity thresholds and required security jobs remain
active. Scanner results, failures and scope limitations are reported separately
from release and acceptance states.
