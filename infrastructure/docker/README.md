# Container build definitions

The six runtime Dockerfiles use exact runtime/toolchain tags, frozen lockfiles, minimized
runtime filesystems, and unprivileged processes. API, worker, MCP, and web use UID/GID
`10001`; PostgreSQL and Redis use the unprivileged users from their pinned upstream
images. No Docker build argument accepts a broker credential. Build from the repository
root:

```bash
docker build -f infrastructure/docker/postgres.Dockerfile -t t212pi-postgres:18.6-hardened .
docker build -f infrastructure/docker/redis.Dockerfile -t t212pi-redis:8.10.1-hardened .
docker build -f infrastructure/docker/api.Dockerfile -t t212pi-api:0.2.0 .
docker build -f infrastructure/docker/worker.Dockerfile -t t212pi-worker:0.2.0 .
docker build -f infrastructure/docker/mcp.Dockerfile -t t212pi-mcp:0.2.0 .
docker build -f infrastructure/docker/web.Dockerfile -t t212pi-web:0.2.0 .
```

The database/coordination derivatives upgrade the affected OpenSSL packages. The
PostgreSQL image also removes unused `gosu` and Debian snake-oil key material before
dropping permanently to `postgres`; Redis drops permanently to `redis`. The Python
application images remove `pip` and `setuptools` from their copied runtime environment,
remove global runtime `pip` and `ensurepip`, while the web runtime removes npm, npx,
Corepack, and global package-manager modules.

The four Bookworm application runtimes install the exact
`libpcre2-8-0=10.42-1+deb12u1` security update before stripping package managers.
Debian's [PCRE2 security update](https://security-tracker.debian.org/tracker/DLA-4772-1)
fixes the older package in the pinned base images. Runtime dpkg metadata remains
available for scanning; package indexes are removed after installation.

`make container-build` builds the complete six-image set used by Compose. Trivy `0.74.0`
scans every image in the required security workflow. A successful build is not a clean
scan claim; record the scanner output at the exact release SHA before release approval.

Historical working-tree runtime probes confirmed that PostgreSQL and Redis can initialize disposable
volumes and become healthy as users `postgres` and `redis`, and that API, worker, MCP, and
web remain operational as non-root after package-manager removal. Trivy `0.74.0` returned
exit `0` for that earlier six-image set. The P208 scan at `7201b53` later detected
two fixable high-severity PCRE2 vulnerabilities in the four Bookworm application
images. The security update above subsequently passed six working-tree image
scans and four exact-version runtime probes. Fresh immutable acceptance remains
required.
Application image IDs are intentionally recorded in release/CI evidence instead
of this build guide because any repository-content change produces a new image ID. Every
external `FROM` image is tag-and-digest pinned. The immutable release-SHA scan rerun is
recorded separately. GitHub Actions remains owner-deferred; local scans are required.
