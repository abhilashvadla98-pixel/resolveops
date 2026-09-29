# ADR-005: Single-service operator console

## Context

Operators need cases, approvals, reliability, audit, and IT request views. The interface is small and
uses the same authentication and APIs as the application.

## Decision

Serve framework-free HTML, CSS, and JavaScript from FastAPI with same-origin requests and no browser
credential persistence.

## Alternatives considered

- Separate React/Vue application: rejected because it adds a build, deployment, dependency, and
  cross-origin security boundary without a present product requirement.

## Consequences

There is one deployable service and no frontend package supply chain. If interaction complexity grows
substantially, this decision should be revisited rather than stretching one script indefinitely.
