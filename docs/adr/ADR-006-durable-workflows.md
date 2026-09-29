# ADR-006: Durable checkpoints plus application lifecycle records

## Context

Approval can pause a workflow beyond one process lifetime. Operators also need a stable status and
audit history independent of graph internals.

## Decision

Use PostgreSQL-backed LangGraph checkpoints for resumable execution and application-owned workflow,
approval, and ordered-event tables for the product lifecycle. Both share the workflow ID.

## Alternatives considered

- Rebuild state from logs: rejected because resume position and interrupt data are easy to lose.
- Build another workflow engine: rejected because LangGraph already supplies the required checkpoint
  semantics.
- Store only graph checkpoints: rejected because they are not the operator-facing audit contract.

## Consequences

Approval survives restart and lifecycle data stays queryable. Two persistence layers must remain
consistent, so terminal writes are idempotent and integration-tested.
