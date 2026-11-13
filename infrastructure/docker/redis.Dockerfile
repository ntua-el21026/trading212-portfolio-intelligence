FROM python:3.13.15-slim-bookworm@sha256:c45a22ea000adfd9cda29364bbe7edd23001ce5cc2ad15857cfbf7766943b9ca AS truststore
FROM redis:8.10.1@sha256:298e5b3bc566bade82f46ad5511777a4a07a294097ce16ada2f6a42be5239df5

USER root
# The pinned Trixie base omits CA roots; bootstrap public trust from a pinned image.
COPY --from=truststore /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
# Resolve exact security packages from an immutable, signature-verified snapshot.
COPY infrastructure/docker/debian-trixie.sources /etc/apt/sources.list.d/debian.sources
RUN apt-get -o Acquire::https::CAInfo=/etc/ssl/certs/ca-certificates.crt update \
    && apt-get -o Acquire::https::CAInfo=/etc/ssl/certs/ca-certificates.crt install --yes --no-install-recommends \
        ca-certificates=20250419+deb13u1 \
        openssl=3.5.7-1~deb13u3 \
    && apt-get -o Acquire::https::CAInfo=/etc/ssl/certs/ca-certificates.crt install --yes --no-install-recommends --only-upgrade \
        apt=3.0.4 \
        libapt-pkg7.0=3.0.4 \
        gzip=1.13-1+deb13u1 \
        libpcre2-8-0=10.46-1~deb13u3 \
        libsqlite3-0=3.46.1-7+deb13u2 \
        libssl3t64=3.5.7-1~deb13u3 \
        openssl-provider-legacy=3.5.7-1~deb13u3 \
        perl-base=5.40.1-6+deb13u1 \
        zlib1g=1:1.3.dfsg+really1.3.1-1+deb13u1 \
    && rm -rf /var/lib/apt/lists/*

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

USER redis
