# ADR-007: Hierarchical agents remain advisory

## Context

The original system used one bounded reasoner inside two deterministic domain workflows. That was
safe and measurable but did not demonstrate planning, autonomous read-tool selection, specialist
handoffs, independent criticism or replanning.

## Decision

Add one global LangGraph Supervisor with customer and employee/IT specialist subgraphs. Use five
justified reasoning roles: Supervisor, Investigation, Policy, Resolution and Critic. Persist each
invocation and read-tool call. Enforce compact contexts, explicit budgets and per-role allowlists.

Keep all sensitive authority outside the agents. Existing deterministic code controls RBAC,
tenancy, arithmetic, approval, state transitions, idempotent writes and final invariants. Critic
acceptance routes a proposal to those controls; it does not authorize an action.

Retain the single reasoner as a cost/complexity baseline. Multi-agent becomes the default only if
measured evaluation demonstrates a worthwhile safety or correctness improvement.

## Consequences

- Planning, tool selection, policy research, proposal and criticism are independently inspectable.
- Normal model-call count and latency increase materially.
- Provider failure surface is larger, so budget stops and escalation are first-class outcomes.
- The architecture can be called multi-agent only for the guarded path, not for executions that use
  the original single-reasoner workflow.
