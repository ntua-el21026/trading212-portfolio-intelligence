# Phase 1 web visual evidence

The checked-in concept images are implementation references, not sources of
financial truth. Frozen repository requirements and the generated
`@trading212/api-contracts` schemas remain authoritative for behavior, copy,
and data semantics.

## References

- `phase-1-desktop.png` — accepted desktop concept, 1536 × 1024.
- `phase-1-mobile.png` — accepted mobile concept, 864 × 1821.

The implementation was compared at the same native output dimensions using
Playwright's pinned Chromium browser. The mobile capture uses a 432 × 910 CSS
viewport at device scale factor 2, producing an 864 × 1820 image.

## Implemented visual mapping

1. The true-white canvas, deep-navy typography, cool-gray rules, and emerald
   trust states follow the accepted palette and restrained financial tone.
2. Desktop retains the accepted sticky top bar, left navigation, central
   portfolio board, allocation visualization, holdings table, and right trust
   rail.
3. Portfolio totals and page titles use an editorial serif face; controls,
   labels, tables, and status text use the system sans-serif stack.
4. Reconciliation, freshness, source cutoff, calculation provenance, and the
   read-only boundary remain visible beside the financial data.
5. Mobile preserves the accepted stacked metric card, compact allocation
   chart/table pairing, holdings continuation, and persistent five-item bottom
   navigation.
6. Keyboard focus, semantic landmarks/tables, a skip link, minimum touch
   targets, overflow containment, and reduced-motion behavior are implemented
   independently of viewport size.

## Intentional copy and data differences

- The concepts contain illustrative values and 30 holdings. The application
  shows only the canonical synthetic fixture returned by the Phase 1 contract:
  five positions, direct holding weights, cash, exact source timestamps, and
  the actual calculation version. It does not invent pagination or totals.
- Required Phase 1 allocation and synchronization routes appear in desktop
  navigation even where the concept uses a shorter route list.
- The mobile header states `Synthetic · read-only`; desktop also carries the
  full synthetic-data notice. These are explicit product-boundary disclosures.
- Dates use the canonical API timestamp and UTC presentation rather than the
  illustrative dates in the concept.
- No Phase 2 optimizer, X-ray, benchmark, report, alert, or Phase 3 research and
  risk claims were added.

## Runtime and API boundary

- Live data is loaded only through the server-side `PortfolioApiClient` and
  `/api/v1`; no browser bundle receives broker credentials or a generic request
  primitive.
- The active account is selected from `listAccounts()`. An optional
  `T212PI_ACCOUNT_ID` must match an account returned for the authenticated
  principal, and multiple accounts otherwise fail closed.
- `T212PI_LOCAL_API_AUTH_ENABLED=1` enables API-issued local sessions only when
  `T212PI_WEB_ENVIRONMENT` is `local` or `test`. The web proxy stores the opaque
  session and CSRF token in strict, HttpOnly cookies and forwards them only on
  server-side API requests.
- `PORTFOLIO_DEMO_MODE=1` enables the deterministic server-side demo fallback
  only in `local` or `test`. It never calls a broker and cannot be enabled in a
  staging or production runtime.
- Without one of those explicit local modes or a valid deployed API session,
  sign-in and portfolio routes fail closed.
