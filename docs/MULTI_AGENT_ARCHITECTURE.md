# Hierarchical multi-agent analysis

ResolveOps now contains a guarded hierarchical analysis path alongside the proven deterministic
customer and IT workflows. The analysis path is explicit and manual: opening a case does not spend
model tokens. An operator chooses **Run multi-agent analysis** when the additional assessment is
useful.

## Roles and authority

| Role | Model responsibility | Tools | Write authority |
|---|---|---|---|
| Supervisor | plan, delegate, stop or replan | none | none |
| Investigation | choose the next useful evidence read in a bounded loop | masked domain reads | none |
| Policy | formulate/follow up hybrid policy searches | policy search | none |
| Resolution | propose issue-separated resolutions | none | none |
| Critic | independently challenge evidence, citations and unsafe proposals | read-only verification | none |

Every role has a distinct prompt, response schema, model invocation, persisted run, trace span,
usage record and tool allowlist. Agent-to-agent handoff occurs through typed LangGraph state, not a
raw chat transcript. A normal supported case uses seven calls: Supervisor; two Investigation turns
around one evidence read; two Policy turns around one retrieval; Resolution; Critic. A model may
finish either loop early, so the actual total can be lower.

The existing deterministic control plane remains authoritative:

```text
operator request
  -> Supervisor
  -> customer or IT specialist subgraph
       -> Investigation read-tool loop
       -> Policy retrieval loop
       -> Resolution proposal
  -> independent Critic
  -> deterministic safety gates
  -> durable human approval when required
  -> idempotent typed executor
  -> fresh-state verification / verify-only recovery
```

Critic acceptance means only “ready for the deterministic control plane.” It never means an action
was authorized or executed. A Critic revision routes back to the Supervisor within the configured
replan and model-call budgets; a rejection or exhausted budget escalates safely.

## Usage controls

- analysis is manual, not triggered by page load;
- role context is scoped and capped at 16,000 characters;
- provider output is capped at 600 tokens per call in the API path;
- default workflow budgets cap agent steps, calls, tools, input/output tokens and wall time;
- tools return masked, source-labelled data and persist only argument hashes/keys;
- tool and model loops have explicit turn limits;
- policy and prior-agent text are always untrusted data;
- the simpler `CaseReasoner` remains available as the low-cost baseline for ablation.

These controls reduce avoidable usage without weakening the deterministic safety boundary. The
22-case offline trajectory run made 182 model-double invocations (8.27 per case) and estimated
71,991 input-context tokens (3,272 per case). It made no provider calls, so dollar cost and live
provider latency remain unknown. The multi-agent path necessarily costs more than the single-call
advisory baseline and is therefore operator-triggered rather than automatic.

## Persistence

Migration `0016_agent_execution_records` adds `agent_runs` and `agent_tool_calls`. Migration
`0017_reviewed_resolution_memory` adds tenant-scoped, expiring memory that can contain only reviewed
resolution patterns. Migration `0018_agent_workflow_jobs` adds durable jobs and a reconnectable event
projection. Raw arguments, secrets and arbitrary model histories are not memory.

Reviewed memory is used by the Resolution role only after investigation and policy retrieval.
Retrieval is tenant scoped, issue typed, expiry limited, and requires every stored policy version to
exactly match the versions retrieved for the current run. The model receives only the typed action,
evidence pattern, verification summary, and policy-version metadata. Memory is advisory context; it
is never treated as current evidence, approval, or authorization.

## Optional external evidence read

`RESOLVEOPS_AGENT_MCP_SERVER_URL` can point a development or isolated demo tenant at one read-only
MCP simulator. The consumer is created for exactly one tenant and currently allows only `get_case`.
An unavailable simulator falls back to the trusted local case reader and labels the source as a
fallback. Tenant mismatch, non-allowlisted tool use, and security denials fail closed; malformed
structured output is treated as an unavailable source. Remote MCP use is rejected in production
until authenticated, tenant-aware transport exists.

## Background execution and live progress

The synchronous endpoint remains available as a compatibility path. When
`RESOLVEOPS_AGENT_QUEUE_ENABLED=true`, the console submits an idempotent job to PostgreSQL and a
separate worker claims it with a time-limited lease. Capacity limits reject new work before an
unbounded backlog forms. Provider failures retry within a fixed attempt budget and then become a
visible dead-letter record; an expired worker lease is recoverable by another worker.

Redis does not contain the case objective, model context, output or result. It carries only a small
wake-up marker and atomic rate-limit counters. PostgreSQL is the durable source of truth, so a Redis
wake-up failure falls back to bounded polling. The authenticated SSE endpoint projects safe job and
role transitions—role name, run identifier, status and token counts, never hidden reasoning. The
console consumes this stream and keeps polling job status as a recovery path.

## Current limitations

The local worker/Redis profile, SSE path, managed-Valkey/worker Terraform, role trajectory gate, and
retrieval/reranking experiments are implemented and tested. A PostgreSQL benchmark claimed 200 jobs
exactly once across eight workers, but it deliberately did not invoke a model. The cloud design has
not been applied, and public hosting, authenticated production MCP transport, live-model multi-agent
quality evidence, calibrated human labels, and multi-hour soak evidence remain unproven.
