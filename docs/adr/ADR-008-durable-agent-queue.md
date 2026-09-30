# ADR-008: PostgreSQL owns agent jobs; Redis coordinates transient work

## Status

Accepted for the optional background-execution profile.

## Context

Multi-agent analysis can exceed an HTTP request lifetime. A production-minded path needs bounded
backpressure, idempotent submission, recoverable worker ownership, visible retry/dead-letter state,
shared rate limiting and reconnectable progress. Putting the entire job payload only in Redis would
make an operational cache the business source of truth and could expose unnecessary case content.

## Decision

- PostgreSQL stores job identity, tenant, objective, status, attempts, lease, result and durable
  progress events.
- A unique tenant/idempotency key makes submission replay-safe.
- Workers claim with a database row lock and `SKIP LOCKED`; a lease permits recovery after a worker
  exits unexpectedly.
- Queue depth is capped. Provider failures use bounded retry and then a visible dead-letter state.
- Redis contains only wake-up markers and atomic token-bucket state. It never carries model prompts,
  case payloads or results.
- Redis failure falls back to PostgreSQL polling and a bounded local limiter. This preserves
  availability but temporarily weakens cross-instance quota coordination, which must be alerted in
  a real deployment.
- SSE reads durable events and exposes structured transitions, not chain-of-thought. Polling remains
  the console recovery path.
- The existing synchronous endpoint remains during migration and local development.

## Consequences

The queue can be inspected and recovered without Redis, and workers cannot silently lose accepted
jobs. PostgreSQL receives additional coordination writes, so worker concurrency and indexes require
measurement before scale claims. Redis and worker deployment add operational cost and are optional;
their AWS infrastructure is not yet implemented.
