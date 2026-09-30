# ADR-009: Reviewed memory and a tenant-bound MCP consumer

## Status

Accepted

## Context

ResolveOps stored human-reviewed resolution patterns but did not use them during multi-agent
analysis. It also exposed a read-only MCP server without proving that an agent runtime could consume
an external evidence interface safely. Passing arbitrary history or unrestricted external tools to
models would create stale-policy, cross-tenant, prompt-injection, and unauthorized-action risks.

## Decision

The Resolution role may receive a small set of reviewed examples only when all of these conditions
hold:

- the memory belongs to the current tenant and issue type;
- it is reviewed and has not expired;
- every stored policy version exactly matches the policy versions retrieved for the current run;
- its resolution conforms to the typed action/approval/notes schema.

Memory is labelled advisory and is never evidence, approval, or execution authority.

The optional MCP consumer is bound to one tenant and one explicit read-tool allowlist. Its first
supported external read is `get_case`. Structured output is validated as a ResolveOps `Case` before
entering agent context. Ordinary availability failures fall back to the trusted local read with an
explicit source marker. Tenant mismatch, forbidden tools, and access denials fail closed. Production
configuration rejects a remote MCP URL until authenticated tenant-aware transport is implemented.

## Consequences

- Reviewed experience can improve proposals without silently overriding current policy.
- Tests can exercise a real MCP client/server boundary and its failure behavior.
- The integration remains intentionally narrow; refunds, policy retrieval, and writes are not
  delegated to the external simulator.
- A future production MCP transport requires authentication, tenant claims, audit correlation,
  timeout/circuit-breaker policy, and deployment-specific threat review.
