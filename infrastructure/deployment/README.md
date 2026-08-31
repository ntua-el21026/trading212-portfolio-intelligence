# Provider-Neutral Deployment Contract

Phase 1 ships immutable non-root images and a provider-neutral deployment
contract; it does not choose a cloud, cluster, domain, identity provider, or
secret manager on the owner's behalf. The local `compose.yaml` is development
orchestration, not a production manifest.

Deploy these independently supervised units:

- API and MCP HTTPS upstreams behind trusted TLS ingress;
- web application;
- worker process;
- one-shot Alembic migration job;
- managed PostgreSQL as the authoritative system of record;
- private Redis as disposable/non-authoritative job coordination where enabled.

Build/tag images from a reviewed release SHA and deploy by immutable digest:

```bash
docker build -f infrastructure/docker/api.Dockerfile -t registry.example/t212pi-api:${RELEASE_SHA} .
docker build -f infrastructure/docker/worker.Dockerfile -t registry.example/t212pi-worker:${RELEASE_SHA} .
docker build -f infrastructure/docker/mcp.Dockerfile -t registry.example/t212pi-mcp:${RELEASE_SHA} .
docker build -f infrastructure/docker/web.Dockerfile -t registry.example/t212pi-web:${RELEASE_SHA} .
```

`RELEASE_SHA` is an operator-supplied reviewed Git SHA; it is not an application
secret. Scan the exact digests before deployment. Supply all runtime values from
the platform, use an external secret-manager adapter, expose only web/API/MCP
ingress, and keep database/Redis/worker private.

Run `alembic -c alembic.ini upgrade head` from the worker image as a controlled
one-shot job before compatible application rollout. Require its success, then
roll out API, worker, MCP, and web; require liveness/readiness and authenticated
synthetic smoke checks. Record SHA, image digests, Alembic head, configuration
revision, backup evidence, and scan/health results.

Production composition is deliberately fail-closed until TLS, exact hosts and
origins, bearer/session authentication, OAuth resource metadata for MCP, managed
PostgreSQL, and an external secret provider are supplied. Public HTTPS/OAuth and
ChatGPT registration remain external acceptance gates, not hidden defaults.

See [Phase 1 Local Operation and Deployment](../../docs/operations/LOCAL_AND_DEPLOYMENT.md)
for the complete rollout/rollback/configuration procedure and
[Backup and Restore](../../docs/operations/BACKUP_RESTORE.md) for recovery.
