FROM python:3.13.15-slim-bookworm@sha256:c45a22ea000adfd9cda29364bbe7edd23001ce5cc2ad15857cfbf7766943b9ca AS truststore
FROM node:24.20.0-bookworm-slim@sha256:ba849c60be29959425b8734d57b8b4b7d56f98edd9504c9af091d5281095a71e AS dependencies
ENV COREPACK_HOME=/corepack
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@10.34.5 --activate
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
COPY apps/web/package.json apps/web/package.json
COPY packages/api-contracts/package.json packages/api-contracts/package.json
COPY packages/ui/package.json packages/ui/package.json
RUN corepack pnpm install --frozen-lockfile

FROM dependencies AS builder
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN corepack pnpm --filter @trading212/web build

FROM node:24.20.0-bookworm-slim@sha256:ba849c60be29959425b8734d57b8b4b7d56f98edd9504c9af091d5281095a71e AS runtime
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
WORKDIR /app
# Node slim omits CA roots; bootstrap only the pinned public trust bundle.
COPY --from=truststore /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app
# Resolve exact security packages from an immutable, signature-verified snapshot.
COPY infrastructure/docker/debian-bookworm.sources /etc/apt/sources.list.d/debian.sources
RUN apt-get -o Acquire::https::CAInfo=/etc/ssl/certs/ca-certificates.crt update \
    && apt-get -o Acquire::https::CAInfo=/etc/ssl/certs/ca-certificates.crt install --yes --no-install-recommends \
        ca-certificates=20250419~deb12u2 \
        openssl=3.0.22-1~deb12u2 \
    && apt-get -o Acquire::https::CAInfo=/etc/ssl/certs/ca-certificates.crt install --yes --no-install-recommends --only-upgrade \
        apt=2.6.2 \
        libapt-pkg6.0=2.6.2 \
        libpcre2-8-0=10.42-1+deb12u2 \
        libssl3=3.0.22-1~deb12u2 \
        perl-base=5.36.0-7+deb12u4 \
    && rm -rf /var/lib/apt/lists/*
RUN rm -rf \
    /usr/local/bin/corepack \
    /usr/local/bin/npm \
    /usr/local/bin/npx \
    /usr/local/lib/node_modules/corepack \
    /usr/local/lib/node_modules/npm
COPY --from=builder --chown=app:app /app/apps/web/.next/standalone ./
COPY --from=builder --chown=app:app /app/apps/web/.next/static ./apps/web/.next/static
COPY --from=builder --chown=app:app /app/apps/web/public ./apps/web/public
# Keep dpkg's status database for vulnerability/license provenance, while
# removing package-manager executables and their fixed helper installations.
RUN for manager_dir in /usr/bin /usr/sbin /usr/local/bin /usr/local/sbin /opt/venv/bin; do \
        rm -f "$manager_dir"/apt* "$manager_dir"/dpkg* \
            "$manager_dir"/npm "$manager_dir"/npx "$manager_dir"/corepack \
            "$manager_dir"/pnpm "$manager_dir"/pnpx \
            "$manager_dir"/yarn "$manager_dir"/yarnpkg \
            "$manager_dir"/uv "$manager_dir"/uvx "$manager_dir"/pip*; \
    done \
    && rm -rf /usr/lib/apt /usr/lib/dpkg /opt/yarn-v* \
        /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack \
        /usr/local/lib/node_modules/pnpm /usr/local/lib/node_modules/yarn \
    && test -s /var/lib/dpkg/status

USER app
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=3 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:3000').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"]
CMD ["node", "apps/web/server.js"]
