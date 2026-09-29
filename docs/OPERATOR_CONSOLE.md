# Operator console

The ResolveOps operator console is a read-only operations interface served by the FastAPI process at
`/console`. It demonstrates the product as an operating system, not just a collection of endpoints.
All displayed business records come from authenticated simulator reads.

## Demonstration flow

1. Migrate and seed the database.
2. Start the API and open `http://127.0.0.1:8000/console`.
3. Select **Connect securely** and enter a configured Operator, Approver, or System API key.
4. Use **Overview** to explain the cross-system case, safety gates, service health, and traceability.
5. Use **Customer Ops** to show separate issue evidence, captured payments, active policy versions,
   tickets, and notifications for `CASE-1001`.
6. Use **Employee & IT** to show the independent approval and access-control evidence for
   `ITCASE-2001`.
7. Use **Reliability** to show authenticated Prometheus request signals and the deterministic control
   boundaries.

The checked-in seed is synthetic. Names, email addresses, case identifiers, orders, payments, and
employee records shown in this demonstration are not real customer or employee data.

## Security boundary

- The API key stays only in JavaScript memory. The console uses neither `localStorage` nor
  `sessionStorage` and clears the input immediately after starting a connection.
- Protected requests use the bearer credential in an authorization header. The key is not placed in
  a URL, DOM record, trace, metric label, or error message.
- The console relies on server-side identity, tenant routing, RBAC, masking, rate limits, and body
  limits. It does not accept a tenant or role from the browser.
- Only operations roles can read `/metrics`. Other authenticated roles continue to receive the
  server's denial instead of UI-created telemetry.
- The Content Security Policy allows only same-origin scripts and styles. No analytics, CDN, remote
  fonts, or third-party browser package is loaded.
- The console performs reads only. Model output cannot approve or execute a refund, message, ticket,
  directory change, or repository grant.

## Visual and browser checks

The console is designed for keyboard access, reduced-motion preferences, desktop navigation, and a
mobile drawer. The implementation was visually checked with populated protected data at desktop and
390-pixel mobile widths. Automated tests verify response headers, local asset delivery, the absence
of persistent browser credential storage, and exclusion of UI assets from the public OpenAPI schema.

Public screenshots must show only seeded synthetic data. Never capture a real
API key, `.env` file, cloud credential, browser password prompt, or private account page.

## Current limits

This is an operator-facing demonstration, not a public end-user application. It has no single sign-on,
browser session cookie, live vendor integration, or mutation control. A production web console would
use an identity provider, short-lived server-managed sessions, CSRF protection where applicable, a
shared gateway rate limit, and deployment-specific CSP/connect-source review.
