# ADR-003: Database-per-tenant isolation

## Context

Authenticated requests must not select arbitrary tenants, and operational records include sensitive
customer and employee data.

## Decision

The authenticated identity resolves a server-side tenant database. Domain tables do not accept a
tenant selector from request bodies. The public demo uses a separate synthetic tenant.

## Alternatives considered

- Shared tables with a tenant column: cheaper at high tenant counts, but every query must preserve a
  row-level isolation invariant.
- Client-selected tenant IDs: rejected because they make authorization depend on untrusted input.

## Consequences

Isolation is simple to reason about, but migrations and connection management occur per tenant and
the approach is less efficient for very large tenant counts.
