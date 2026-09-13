FROM postgres:18.6@sha256:4ef4dbc939d61acea57712655ddb4b4ab27419c913f94cca0cd57cb3ea3c2280

USER root
RUN apt-get update \
    && apt-get install --yes --no-install-recommends --only-upgrade \
        gzip=1.13-1+deb13u1 \
        libpcre2-8-0=10.46-1~deb13u2 \
        libperl5.40=5.40.1-6+deb13u1 \
        libsqlite3-0=3.46.1-7+deb13u2 \
        libssl3t64=3.5.7-1~deb13u2 \
        openssl=3.5.7-1~deb13u2 \
        openssl-provider-legacy=3.5.7-1~deb13u2 \
        perl=5.40.1-6+deb13u1 \
        perl-base=5.40.1-6+deb13u1 \
        perl-modules-5.40=5.40.1-6+deb13u1 \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f \
        /etc/ssl/certs/ssl-cert-snakeoil.pem \
        /etc/ssl/private/ssl-cert-snakeoil.key \
        /usr/local/bin/gosu

# The inherited entrypoint supports an already-unprivileged process. The data
# and socket directories are owned by this user in the pinned upstream image.
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

USER postgres
