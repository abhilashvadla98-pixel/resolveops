# ADR-001: Advisory model reasoning with deterministic actions

## Context

Case evidence and policy benefit from concise synthesis, but refunds and access grants require exact
authorization, idempotency, and verification.

## Decision

Model output is a typed advisory assessment only. Deterministic code owns calculations, permissions,
approval limits, action calls, state transitions, and fresh-state verification.

## Alternatives considered

- Give the model action tools: rejected because recommendation quality is not authorization.
- Remove model reasoning: viable fallback, but loses useful evidence synthesis.

## Consequences

The system works without a model and fails closed on provider or citation errors. More deterministic
code is required, but sensitive behavior is directly testable.
