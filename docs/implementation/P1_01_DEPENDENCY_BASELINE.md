# P1-01 Dependency Baseline and Registry Evidence

**Status:** Implemented, acceptance in progress
**Reviewed:** 2026-08-31
**Authority:** Exact P1-01 dependency selection under `PHASE_1_TECHNICAL_BASELINE.md`

This note records the primary registry evidence used to create `uv.lock` and `pnpm-lock.yaml`. It does not mark P1-01 complete: clean-environment CI and the remaining Phase 1 work must still supply acceptance evidence.

## Runtime and container pins

| Component | Exact pin | Primary source checked |
|---|---:|---|
| Python | `3.13.15` | [python.org release artifact](https://www.python.org/ftp/python/3.13.15/Python-3.13.15.tgz) |
| Node.js | `24.20.0` | [nodejs.org release artifact](https://nodejs.org/dist/v24.20.0/node-v24.20.0-linux-x64.tar.xz) and [SHA-256 manifest](https://nodejs.org/dist/v24.20.0/SHASUMS256.txt) |
| pnpm | `10.34.5` | [npm registry metadata](https://registry.npmjs.org/pnpm/10.34.5) |
| PostgreSQL | `postgres:18.6` | [Docker Official Image tag metadata](https://hub.docker.com/v2/repositories/library/postgres/tags/18.6) |
| Redis | `redis:8.10.1` | [Docker Official Image tag metadata](https://hub.docker.com/v2/repositories/library/redis/tags/8.10.1) |
| Semgrep CE | `1.175.0` plus pinned image digest | [official Semgrep image](https://hub.docker.com/r/semgrep/semgrep) |
| Trivy | `0.74.0` plus pinned action commit | [official Trivy release](https://github.com/aquasecurity/trivy/releases/tag/v0.74.0) |

Redis is optional and non-authoritative. Canonical financial data, checkpoints, and acceptance evidence remain in PostgreSQL.

Compose derives hardened local PostgreSQL and Redis images from these exact upstream
tags. The derived images upgrade the affected OpenSSL packages and run as the upstream
unprivileged users; the PostgreSQL image also removes unused `gosu` and Debian snake-oil
key material. Python runtime images exclude `pip` and `setuptools`, and the web runtime
excludes npm, npx, Corepack, and global package-manager modules. The Python runtime stage
also removes global `pip` and `ensurepip`, preventing the base interpreter's unused
installer from reintroducing vulnerable package metadata. Final Trivy evidence is
recorded separately from this dependency/remediation architecture.

GitHub code-scanning upload is unavailable for this user-owned private repository under
its current entitlement. The required substitute is a deterministic Semgrep CE scan:
the exact container digest is pinned in `Makefile` and `.github/workflows/security.yml`,
rules are repository-local in `.semgrep.yml`, metrics are disabled, and CI runs without
network access or external uploads. Trivy `0.74.0` scans the repository and every runtime
image at high/critical severity with unfixed findings excluded. `trivy.yaml` documents
the bounded `LGPL-3.0-or-later` acceptance for unmodified sharp/libvips in this private
release; public distribution requires a fresh obligations review.

All GitHub Actions dependencies are pinned to immutable commit SHAs. Every external
Docker `FROM` reference is pinned by both readable version tag and immutable digest. The
working-tree scan used Trivy image digest
`sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969`;
release evidence still requires the same gates at the immutable `main` SHA.

## Python direct pins

Each link is version-specific metadata from PyPI, the official Python package registry.

| Runtime package | Pin | Registry evidence |
|---|---:|---|
| FastAPI | `0.141.1` | [PyPI](https://pypi.org/pypi/fastapi/0.141.1/json) |
| Pydantic | `2.13.5` | [PyPI](https://pypi.org/pypi/pydantic/2.13.5/json) |
| pydantic-settings | `2.15.0` | [PyPI](https://pypi.org/pypi/pydantic-settings/2.15.0/json) |
| SQLAlchemy | `2.0.52` | [PyPI](https://pypi.org/pypi/SQLAlchemy/2.0.52/json) |
| Alembic | `1.19.1` | [PyPI](https://pypi.org/pypi/Alembic/1.19.1/json) |
| psycopg | `3.3.4` | [PyPI](https://pypi.org/pypi/psycopg/3.3.4/json) |
| httpx | `0.28.1` | [PyPI](https://pypi.org/pypi/httpx/0.28.1/json) |
| Celery | `5.6.3` | [PyPI](https://pypi.org/pypi/Celery/5.6.3/json) |
| MCP Python SDK | `2.1.1` | [PyPI](https://pypi.org/pypi/mcp/2.1.1/json) |
| PyYAML | `6.0.3` | [PyPI](https://pypi.org/pypi/PyYAML/6.0.3/json) |
| structlog | `26.1.0` | [PyPI](https://pypi.org/pypi/structlog/26.1.0/json) |
| prometheus-client | `0.26.0` | [PyPI](https://pypi.org/pypi/prometheus-client/0.26.0/json) |
| OpenTelemetry API/SDK | `1.44.0` | [API](https://pypi.org/pypi/opentelemetry-api/1.44.0/json), [SDK](https://pypi.org/pypi/opentelemetry-sdk/1.44.0/json) |
| PyJWT | `2.13.0` | [PyPI](https://pypi.org/pypi/PyJWT/2.13.0/json) |
| cryptography | `50.0.1` | [PyPI](https://pypi.org/pypi/cryptography/50.0.1/json) |

| Development package | Pin | Registry evidence |
|---|---:|---|
| pytest | `9.1.1` | [PyPI](https://pypi.org/pypi/pytest/9.1.1/json) |
| pytest-asyncio | `1.4.0` | [PyPI](https://pypi.org/pypi/pytest-asyncio/1.4.0/json) |
| Hypothesis | `6.167.1` | [PyPI](https://pypi.org/pypi/Hypothesis/6.167.1/json) |
| Ruff | `0.16.5` | [PyPI](https://pypi.org/pypi/Ruff/0.16.5/json) |
| mypy | `2.3.1` | [PyPI](https://pypi.org/pypi/mypy/2.3.1/json) |
| coverage | `7.16.0` | [PyPI](https://pypi.org/pypi/coverage/7.16.0/json) |

The build/runtime support pins are `uv_build==0.12.7`, `uvicorn==0.41.0`, and `types-PyYAML==6.0.12.20260815`; each is also exact in the workspace metadata/lock.

## TypeScript direct pins

Each link is version-specific metadata from the official npm registry.

| Package | Pin | Registry evidence |
|---|---:|---|
| Next.js | `16.3.3` | [npm](https://registry.npmjs.org/next/16.3.3) |
| React / React DOM | `19.2.8` | [React](https://registry.npmjs.org/react/19.2.8), [React DOM](https://registry.npmjs.org/react-dom/19.2.8) |
| TypeScript compiler | `7.0.2` | [npm](https://registry.npmjs.org/typescript/7.0.2) |
| ESLint | `10.9.1` | [npm](https://registry.npmjs.org/eslint/10.9.1) |
| eslint-config-next | `16.3.3` | [npm](https://registry.npmjs.org/eslint-config-next/16.3.3) |
| Vitest | `4.1.11` | [npm](https://registry.npmjs.org/vitest/4.1.11) |
| Vite React plugin | `6.1.1` | [npm](https://registry.npmjs.org/%40vitejs%2Fplugin-react/6.1.1) |
| Testing Library React | `16.3.3` | [npm](https://registry.npmjs.org/%40testing-library%2Freact/16.3.3) |
| Testing Library jest-dom | `7.0.1` | [npm](https://registry.npmjs.org/%40testing-library%2Fjest-dom/7.0.1) |
| Testing Library user-event | `14.6.6` | [npm](https://registry.npmjs.org/%40testing-library%2Fuser-event/14.6.6) |
| Playwright Test | `1.62.1` | [npm](https://registry.npmjs.org/%40playwright%2Ftest/1.62.1) |
| decimal.js | `10.6.0` | [npm](https://registry.npmjs.org/decimal.js/10.6.0) |
| lucide-react | `1.38.0` | [npm](https://registry.npmjs.org/lucide-react/1.38.0) |
| Recharts | `3.10.1` | [npm](https://registry.npmjs.org/recharts/3.10.1) |
| Zod | `4.5.4` | [npm](https://registry.npmjs.org/zod/4.5.4) |

Prettier, Vite, jsdom, `@eslint/js`, the Next and React Hooks ESLint plugins, and the React/Node type packages are exact support pins in `package.json` files and the lockfile. The official [`@typescript/typescript6` compatibility API](https://registry.npmjs.org/%40typescript%2Ftypescript6/6.0.2) is pinned to `6.0.2` for tools that programmatically embed the compiler.

## Compatibility result and bounded peer exception

- Every selected Python release advertises support for Python 3.13 through its `requires-python` range, and `uv lock --python 3.13.15` resolved the complete workspace.
- Next.js `16.3.3`, ESLint `10.9.1`, Vitest `4.1.11`, the React Vite plugin `6.1.1`, Playwright `1.62.1`, and pnpm `10.34.5` all advertise Node 24-compatible engine ranges.
- TypeScript 7.0 intentionally does not ship a programmatic compiler API. Following the [official TypeScript 7 side-by-side guidance](https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/#running-side-by-side-with-typescript-6-0), application packages install `typescript@7.0.2` normally while the root lint-tool workspace exposes `@typescript/typescript6@6.0.2` through its `typescript` alias for `typescript-eslint`. Next uses its supported `experimental.useTypeScriptCli` path so production builds execute the TypeScript 7 compiler. Lint and build therefore both remain executable instead of either being skipped.
- Some transitive ESLint plugins still publish peer ranges ending before ESLint 10. `pnpm-workspace.yaml` retains strict peer enforcement while allowing only the explicit `eslint: 10` major required by this baseline. No general peer-dependency bypass is enabled.
- The `eslint-plugin-react` release transitively bundled by `eslint-config-next==16.3.3` still calls an API removed by ESLint 10. The web flat config therefore uses the compatible ESLint 10 core, `eslint-config-next/typescript`, `@next/eslint-plugin-next`, and `eslint-plugin-react-hooks` configs directly. Next core-web-vitals and Hooks rules remain active; lint is not skipped or converted to a no-op.
- The Node archive was checked against the official SHA-256 manifest before generating and installing `pnpm-lock.yaml` with Node `24.20.0` and pnpm `10.34.5`.
