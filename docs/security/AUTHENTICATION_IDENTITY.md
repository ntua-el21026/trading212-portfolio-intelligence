# Authentication identity contract

R-01 remediation contract, recorded before the production fix. This narrows
claim conversion and corrects external identity handling without changing owner
mapping, scopes, the broker allowlist, or the MCP tool registry.

## Field semantics and compatibility

- Internal `principal_id` and `owner_id` retain their existing nonempty 1..255
  character ASCII grammar: `[A-Za-z0-9._:-]+`.
- External `iss` and `sub` follow RFC 7519 StringOrURI semantics. They are
  nonempty strings of at most 255 Unicode code points, matching the existing
  database columns. Unicode control, format, surrogate, and line/paragraph
  separator characters are rejected. A colon requires RFC 3986 URI syntax;
  otherwise opaque subjects such as `provider|synthetic-subject` are valid.
- Identity comparison and storage are exact and case sensitive. Do not trim,
  lowercase, normalize Unicode, percent-decode, canonicalize a URL, or append a
  slash. A URI identity is never fetched and cannot select a key or JWKS URL.
- Trusted tokens must supply `owner_id`. Explicit `principal_id` claims must
  satisfy the internal grammar. The legacy fallback is retained only when
  `principal_id` is absent and `sub` itself satisfies that grammar. An explicitly
  null/empty/malformed principal claim now fails closed; it cannot silently
  activate the fallback. External subjects that need an internal identifier
  require that explicit trusted claim. No external-to-owner lookup is invented.
- `iat`, `exp`, and optional `nbf` must be finite JSON numbers representable as
  timezone-aware UTC datetimes. Fractional seconds are allowed; booleans, numeric
  strings, objects, arrays, nulls and out-of-range values are rejected. This
  deliberately removes incidental integer coercion by the JWT library. After
  signature/issuer/audience/required-claim verification, the shared authenticator
  performs all three time checks against its timezone-aware clock with the same
  bounded skew. This preserves fractional expiry until its actual instant;
  PyJWT's integer-only time checks are replaced, not relied on as a fallback.
  Precision is the application's UTC datetime precision (microseconds).
- Existing optional `sid` handling is unchanged: a string is retained and other
  types are ignored. Session authorization still uses the validated principal
  and server-side session expiry/revocation, never `sid` as an ownership claim.

## Verification and transport

Signature verification remains restricted to RS256, ES256 and EdDSA using the
configured trusted public key, issuer and audience. Required claims, expiry,
issued-at, optional not-before and configured bounded clock skew are enforced.
Unknown or empty scopes fail authentication; application scopes and current
owner/account grants still apply after successful authentication.

Malformed bearer credentials produce a bounded authentication error without a
chained decoder/conversion exception or claim contents. The API maps it to its
existing sanitized 401 envelope. MCP uses SharedTokenVerifier and
PrincipalResolver over the same validated principal, retaining only a token
fingerprint in request context. The MCP SDK also receives its required integer
expiry as a secondary coarse check; the verifier and reconstructed principal
retain the exact UTC expiry and reject it at the shared boundary.

The MCP authorization-server metadata additionally requires an HTTP(S) issuer
URL: HTTPS except explicit loopback HTTP for local tests, with no credentials,
query or fragment. The SDK receives a validated URL whose serialized identity
is the exact configured string, including an absent trailing slash. This
transport profile does not alter the shared JWT StringOrURI contract.

Real signed tests generate asymmetric private keys and bearer credentials only
in memory; failure messages and evidence contain neither. The API transport
uses the real authenticator. MCP Streamable HTTP additionally exercises real
PostgreSQL grants and application command persistence. Local results do not
constitute independent acceptance or deployed credential validation.

References: [RFC 7519 sections 2 and 4.1](https://www.rfc-editor.org/rfc/rfc7519.html),
[RFC 3986 URI grammar](https://www.rfc-editor.org/rfc/rfc3986.html#appendix-A).

## MCP 2.2 compatibility clarification, 2026-11-13

The SDK receives explicit `validate_token_resource=False`, retaining its previous
effective behavior. `JwtAuthenticator` verifies the configured issuer, audience
and signature before `SharedTokenVerifier` produces an access token. The OAuth
resource URL describes the transport; it does not replace the configured JWT
audience, which may be a different StringOrURI value. No warning is suppressed.
Signed transport regressions cover RS256, ES256 and EdDSA: the configured
audience succeeds, while a substituted resource URL or other audience receives
401. Existing PostgreSQL transport regressions additionally require no command
execution or persistence for invalid bearer credentials.
