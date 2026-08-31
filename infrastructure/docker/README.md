# Container build definitions

The six runtime Dockerfiles use exact runtime/toolchain tags, frozen lockfiles, minimized
runtime filesystems, and unprivileged processes. API, worker, MCP, and web use UID/GID
`10001`; PostgreSQL and Redis use the unprivileged users from their pinned upstream
images. No Docker build argument accepts a broker credential. Build from the repository
root:

```bash
docker build -f infrastructure/docker/postgres.Dockerfile -t t212pi-postgres:18.6-hardened .
docker build -f infrastructure/docker/redis.Dockerfile -t t212pi-redis:8.10.1-hardened .
docker build -f infrastructure/docker/api.Dockerfile -t t212pi-api:0.1.0 .
docker build -f infrastructure/docker/worker.Dockerfile -t t212pi-worker:0.1.0 .
docker build -f infrastructure/docker/mcp.Dockerfile -t t212pi-mcp:0.1.0 .
docker build -f infrastructure/docker/web.Dockerfile -t t212pi-web:0.1.0 .
```

The database/coordination derivatives upgrade the affected OpenSSL packages. The
PostgreSQL image also removes unused `gosu` and Debian snake-oil key material before
dropping permanently to `postgres`; Redis drops permanently to `redis`. The Python
application images remove `pip` and `setuptools` from their copied runtime environment,
remove global runtime `pip` and `ensurepip`, while the web runtime removes npm, npx,
Corepack, and global package-manager modules.

`make container-build` builds the complete six-image set used by Compose. Trivy `0.74.0`
scans every image in the required security workflow. A successful build is not a clean
scan claim; record the scanner output at the exact release SHA before release approval.

Working-tree runtime probes confirmed that PostgreSQL and Redis can initialize disposable
volumes and become healthy as users `postgres` and `redis`, and that API, worker, MCP, and
web remain operational as non-root after package-manager removal. Trivy `0.74.0` returned
exit `0` with no high/critical vulnerability or secret findings for all six working-tree
images. Application image IDs are intentionally recorded in release/CI evidence instead
of this build guide because any repository-content change produces a new image ID. Every
external `FROM` image is tag-and-digest pinned. The immutable release-SHA scan rerun is
recorded separately when CI executes it.
