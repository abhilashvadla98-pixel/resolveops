# ResolveOps integration interfaces

## MCP boundary

ResolveOps exposes a deliberately small, read-only MCP server over standard input/output. Install
the `interfaces` optional dependency and start it with `resolveops-mcp`. The server reuses the
existing typed internal contracts and currently exposes:

- `get_case`
- `get_refund`
- `search_policies`
- `get_workflow_status`
- `get_operation_recovery_plan`

Every MCP tool is marked read-only, non-destructive, idempotent, and closed-world. Those annotations
help clients describe behavior; ResolveOps still enforces the actual boundary by registering no
write tools. Refund creation, notification delivery, ticket creation, approval decisions, and
workflow mutation remain internal. They must not be exposed through MCP until a tenant-aware
authenticated transport is added. The local server uses an Agent actor and therefore receives
masked PII through internal reads.

The default server uses deterministic local feature-hash embeddings. It does not call an external
model or service. It connects to the database configured by `RESOLVEOPS_DATABASE_URL`.

The multi-agent runtime can optionally consume `get_case` from one tenant-bound read-only simulator
through `RESOLVEOPS_AGENT_MCP_SERVER_URL`. This is a development/demo integration, not a production
remote trust boundary. The consumer rejects cross-tenant calls and every tool outside its explicit
allowlist. Availability failures use a source-labelled local read fallback; access denials do not.

## Refund status webhook

`POST /events/v1/refund-status` accepts the one event type that currently has a justified external
producer: status changes from a payment/refund provider. It does not create refunds or authorize
money movement.

For a single local tenant, configure a random secret containing at least 32 characters in
`RESOLVEOPS_WEBHOOK_SECRET`. For multiple tenants, configure
`RESOLVEOPS_WEBHOOK_SECRETS_JSON` as a tenant-to-secret object. Every tenant must have a different
secret. Producers send the raw JSON body with:

- `X-ResolveOps-Tenant`: the configured tenant ID whose secret signs the event
- `X-ResolveOps-Timestamp`: Unix time in seconds
- `X-ResolveOps-Signature`: `sha256=` plus the hexadecimal HMAC-SHA256 of
  `<timestamp>.<raw-body>`

The default replay window is 300 seconds and can be changed, up to one hour, with
`RESOLVEOPS_WEBHOOK_TOLERANCE_SECONDS`.

Authenticated, schema-valid events are durably recorded. Event IDs are idempotent: an exact replay
returns the stored result, while reuse of the same ID for different content returns a conflict.
Each refund has a durable ordering cursor. Older or equal-time events are stored but ignored, and
terminal refund states cannot be regressed. Invalid state transitions are stored as rejected so an
operator can diagnose them without repeatedly applying them.

The tenant selects both its HMAC verifier and its physically separate database. A signature made
with one tenant's secret is rejected for every other tenant. Provider identity lifecycle, TLS,
network exposure, gateway-level shared quotas, and secret-manager integration remain deployment
responsibilities. The application-level request-size and rate limits apply to this endpoint before
signature verification.
