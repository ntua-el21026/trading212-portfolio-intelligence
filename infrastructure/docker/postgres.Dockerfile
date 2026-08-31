FROM postgres:18.6@sha256:4ef4dbc939d61acea57712655ddb4b4ab27419c913f94cca0cd57cb3ea3c2280

USER root
RUN apt-get update \
    && apt-get install --yes --no-install-recommends --only-upgrade \
        libssl3t64=3.5.7-1~deb13u2 \
        openssl=3.5.7-1~deb13u2 \
        openssl-provider-legacy=3.5.7-1~deb13u2 \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f \
        /etc/ssl/certs/ssl-cert-snakeoil.pem \
        /etc/ssl/private/ssl-cert-snakeoil.key \
        /usr/local/bin/gosu

# The inherited entrypoint supports an already-unprivileged process. The data
# and socket directories are owned by this user in the pinned upstream image.
USER postgres
