FROM redis:8.10.1@sha256:298e5b3bc566bade82f46ad5511777a4a07a294097ce16ada2f6a42be5239df5

USER root
RUN apt-get update \
    && apt-get install --yes --no-install-recommends --only-upgrade \
        libssl3t64=3.5.7-1~deb13u2 \
        openssl-provider-legacy=3.5.7-1~deb13u2 \
    && rm -rf /var/lib/apt/lists/*

USER redis
