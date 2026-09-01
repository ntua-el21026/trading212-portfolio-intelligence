# Credentials, Rotation, and Trading 212 Demo Validation

**Status:** Phase 1 operational contract
**External gate:** Trading 212 Demo smoke is `blocked_external` until the owner
supplies a dedicated read-only Demo credential and executes the probe.

## 1. Credential contract

- Use a dedicated, revocable Trading 212 Demo credential for validation.
- Never paste a key/secret into source, a command argument, a URL, browser
  storage, ChatGPT, MCP input/output, logs, traces, screenshots, or a review artifact.
- Browser, API responses, MCP results, Redis/Celery messages, and canonical
  database records never contain the credential value.
- Local/test resolution accepts one allowlisted environment variable containing
  exactly two JSON string fields: `api_key` and `api_secret`.
- Staging/production requires an external secret-manager adapter. Environment
  storage is not an accepted production backend.
- An opaque reference may be stored with a broker connection; resolution happens
  only at the outbound provider boundary.

The committed `.env.example` leaves every sensitive value blank. Do not put a
real credential in `.env` for routine synthetic development.

## 2. Demo-only smoke behavior

[`scripts/smoke_trading212_demo.py`](../../scripts/smoke_trading212_demo.py)
requires the explicit gate `T212PI_RUN_TRADING212_DEMO_SMOKE=1`. It has no CLI
credential arguments and no Live execution path. It rejects a surrounding Live
selection before transport, pins the provider client to
`https://demo.trading212.com/api/v0`, disables retries, and dispatches only:

```text
GET /equity/account/summary
GET /equity/positions
```

Successful output contains only the Demo environment/origin, capability names,
HTTP status, observation times, rate-limit-header presence, and record counts.
It omits account IDs, currency/balances, position contents, response bodies,
source hashes, authorization material, and error details. Exit codes are `0` for
pass, `1` for a sanitized provider/internal failure, and `2` for missing opt-in
or invalid/missing configuration.

## 3. Exact owner procedure

Use a private local shell only after `PROJECT_STATUS.json` records the designated
corrected release SHA and the owner-run Demo gate is ready. The steps below fetch and
prune the remote, switch to authoritative `main`, update it by fast-forward only, verify
that the checkout is exactly the designated release SHA, disable interactive history,
read the secret without echo, create the strict JSON bundle without placing either value
in an argument, run the probe, and remove all shell variables afterward:

```bash
cd /home/peppaspan/trading212-portfolio-intelligence
git fetch origin --prune
git switch main
git pull --ff-only origin main
designated_release_sha="$(
  python3 - <<'PY'
import json
from pathlib import Path

status = json.loads(Path("PROJECT_STATUS.json").read_text(encoding="utf-8"))
value = status.get("release_candidate_sha")
if not isinstance(value, str) or len(value) != 40:
    raise SystemExit("PROJECT_STATUS.json does not contain a designated release SHA")
print(value)
PY
)"
test "$(git rev-parse HEAD)" = "${designated_release_sha}"
set +o history
read -r -s -p 'Trading 212 Demo API key: ' demo_api_key
printf '\n'
read -r -s -p 'Trading 212 Demo API secret: ' demo_api_secret
printf '\n'
export T212PI_TRADING212_CREDENTIAL_BUNDLE="$(
  DEMO_API_KEY="${demo_api_key}" DEMO_API_SECRET="${demo_api_secret}" python3 - <<'PY'
import json
import os

print(json.dumps({
    "api_key": os.environ["DEMO_API_KEY"],
    "api_secret": os.environ["DEMO_API_SECRET"],
}, separators=(",", ":")))
PY
)"
unset demo_api_key demo_api_secret
export T212PI_TRADING212_ENVIRONMENT=demo
export T212PI_TRADING212_LIVE_ENABLED=false
export T212PI_RUN_TRADING212_DEMO_SMOKE=1
make smoke-trading212-demo
smoke_exit=$?
unset T212PI_TRADING212_CREDENTIAL_BUNDLE
unset T212PI_TRADING212_ENVIRONMENT
unset T212PI_TRADING212_LIVE_ENABLED
unset T212PI_RUN_TRADING212_DEMO_SMOKE
unset designated_release_sha
set -o history
test "${smoke_exit}" -eq 0
```

Record the sanitized JSON result, UTC time, release SHA, and command exit status.
Do not record shell history, environment output, request headers, raw responses,
or portfolio data. A successful probe establishes only these two Demo GET
contracts; it is not Live validation and not evidence that a full durable refresh
completed.

## 4. Full worker connection

Synthetic mode remains the default. A durable Trading 212 refresh additionally
requires an authorized broker connection/account whose opaque credential
reference resolves at the worker boundary, `T212PI_WORKER_PROVIDER=trading212`,
and `T212PI_TRADING212_ENVIRONMENT=demo`. The Phase 1 browser and MCP app do not
accept broker credentials. Connection provisioning and the external
secret-manager adapter are deployment responsibilities; do not work around them
with a generic API route or database plaintext.

## 5. Rotation and revocation

1. Pause new provider refreshes while cached canonical reads remain available.
2. Create a new dedicated read-only Demo credential and update the existing
   secret-manager version/reference atomically.
3. Run the Demo-only smoke in an isolated operator shell.
4. Restart or roll workers only if the secret adapter does not support safe
   version refresh; verify redacted authentication events and a reconciled run.
5. Revoke the old credential at Trading 212 and confirm it can no longer be used.
6. Record non-sensitive key metadata, timestamps, actor, reason, affected service,
   and validation result.

For suspected exposure, revoke first, disable provider egress, preserve evidence,
scan source/artifacts/logs/traces/backups, rotate application credentials where
scope may overlap, and reconcile portfolio data before resuming ingestion.
