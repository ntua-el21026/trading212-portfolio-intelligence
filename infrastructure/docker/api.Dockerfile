FROM ghcr.io/astral-sh/uv:0.12.7@sha256:95f2aa1fe59274951cfe9b0cbc7972e879ff1004bc8945d130a32eb0dbd85945 AS uv
FROM python:3.13.15-slim-bookworm@sha256:c45a22ea000adfd9cda29364bbe7edd23001ce5cc2ad15857cfbf7766943b9ca AS builder

COPY --from=uv /uv /uvx /usr/local/bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /build
COPY . .
RUN uv sync --frozen --no-dev --package trading212-api --no-editable \
    && rm -rf \
        /opt/venv/bin/pip* \
        /opt/venv/lib/python3.13/site-packages/pip \
        /opt/venv/lib/python3.13/site-packages/pip-* \
        /opt/venv/lib/python3.13/site-packages/setuptools \
        /opt/venv/lib/python3.13/site-packages/setuptools-*

FROM python:3.13.15-slim-bookworm@sha256:c45a22ea000adfd9cda29364bbe7edd23001ce5cc2ad15857cfbf7766943b9ca AS runtime
ENV PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
# Apply the Bookworm PCRE2 security update before removing package managers.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends --only-upgrade \
        libpcre2-8-0=10.42-1+deb12u1 \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home app \
    && rm -rf \
        /usr/local/bin/pip* \
        /usr/local/lib/python3.13/ensurepip \
        /usr/local/lib/python3.13/site-packages/pip \
        /usr/local/lib/python3.13/site-packages/pip-*
COPY --from=builder --chown=app:app /opt/venv /opt/venv
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
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3).read()"]
CMD ["uvicorn", "trading212_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]
