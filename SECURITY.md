# Security Policy

## Scope

This public repository contains proprietary portfolio-intelligence software. Public
source visibility does not grant reuse rights beyond [LICENSE.md](LICENSE.md).
Security issues include credential exposure, unauthorized portfolio access,
financial calculation integrity defects, provider-contract bypass, and any path
that could cause a Trading 212 write.

## Critical invariant

The product is strictly read-only with respect to Trading 212. Any observed or attempted broker request using a method other than `GET`, any non-allowlisted path, any order/Pie mutation capability, or any credential exposure is a critical security incident even when the upstream provider rejects it.

## Reporting

Do not open a public issue containing a secret, account identifier, portfolio data, exploit detail, or private log. Revoke/rotate affected credentials first, preserve sanitized evidence, and notify the repository owner through a private channel.

A useful report includes:

- affected commit/version/environment;
- safe reproduction steps;
- expected versus observed behavior;
- impact and whether secrets/private data may be involved;
- sanitized logs/correlation IDs;
- mitigation already performed.

Never include real Trading 212 API credentials.

## Response priorities

1. Revoke/rotate exposed broker/application/deployment credentials.
2. Disable affected ingress/egress or service capability.
3. Preserve audit evidence without spreading private data.
4. Confirm whether broker-write/default-deny boundary was crossed.
5. Correct the defect with regression/security tests.
6. Validate canonical portfolio/calculation integrity.
7. Document root cause, impact, recovery, and prevention.

## Supported versions

Until `1.0.0`, only the current `main` baseline/active phase is supported. After releases begin, the support matrix will be maintained here and in the changelog.

## Security design

See:

- `docs/security/SECURITY_ARCHITECTURE.md`
- `docs/security/PRIVACY_RETENTION_AUDIT.md`
- `docs/integrations/TRADING212_API_CONTRACT.md`
- `docs/engineering/DEPLOYMENT_OPERATIONS.md`
