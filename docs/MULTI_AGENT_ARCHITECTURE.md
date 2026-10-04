# Hierarchical multi-agent analysis

ResolveOps integrates guarded hierarchical analysis into the normal customer workflow. Opening a
case does not spend model tokens. When an operator starts an investigation, deterministic routing
selects the bounded graph for multiple issues or an investigation-evidence error. Refund amount
alone does not trigger agents. Simple supported cases remain rules-only. Both paths enter the same
deterministic control plane. The employee repository-access workflow is deterministic; a separate
IT reasoning contract is not proof that the employee API invokes agents.

## Roles and authority

| Role | Model responsibility | Tools | Write authority |
|---|---|---|---|
| Supervisor | structure issues and evidence tasks; bounded replanning | none | none |
| Investigation | choose the next useful evidence read in a bounded loop | masked domain reads | none |
| Policy | formulate/follow up hybrid policy searches | policy search | none |
| Resolution | propose issue-separated resolutions | none | none |
| Critic | independently challenge the supplied evidence and proposed action | no autonomous tool loop before execution | none |

Every role has a distinct prompt, response schema, model invocation, persisted run, trace span,
usage record and tool allowlist. Agent-to-agent handoff occurs through typed LangGraph state, not a
raw chat transcript. The route is sequential, not unrestricted supervisor-selected delegation.
After contradictory source evidence, policy/resolution/critic are skipped. Missing or conflicting
policy skips resolution/critic. These deterministic stops return `status=escalated`, explicit
`skipped_roles` and `stop_reason`, and null outputs for roles that never ran. They cannot masquerade
as a critic acceptance. Otherwise the resolution and independent critic execute normally.

The investigator chooses useful reads within its budget, but must read the case/order, linked
captures, relevant return and existing refunds for the reported issues. Existing refunds can be
discovered even when opened on another case. It cannot claim completion from a fixture finding or
a customer statement alone. A six-read investigation needs at least seven investigator calls;
the old seven-call fixture smoke is not a realistic full-case cost estimate.

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

Per-issue recommendations explicitly say `refund`, `wait`, `no_action`, `request_information` or
`escalate`. A refund action must match the server-derived eligible payment and amount. A missing
matching issue, refusal, uncertainty, or unsupported action stops execution. Investigation never
writes a refund. Approval and verified submission are separate from settlement: a pending refund
remains open until the provider event confirms the final state. Demo provider events are synthetic.

Evidence references bind to the exact tool observation, source/time, scalar JSON pointer and value;
the server reconstructs factual text from the source value. Policy citations remain the model's
selected chunks and are checked against actual retrieved versions/effective dates. Typed
`selected_policy_versions` entries avoid provider schema limitations with arbitrary dictionary
keys; normalization does not add unselected policy citations or versions.

## Usage controls

- analysis starts only when the operator starts an investigation, never on page load;
- role context is scoped and capped at 16,000 characters;
- integrated provider output is capped at 1,600 tokens per call;
- default workflow budgets cap agent steps, calls, tools, input/output tokens and wall time;
- tools are bound to the workflow's case and order; cross-case/customer/order/payment/return/refund
  reads are denied, including switching from a customer case to an IT snapshot;
- tools return masked, source-labelled data; normal telemetry persists argument hashes/keys,
  whereas the synthetic evaluation harness explicitly retains source observations;
- tool and model loops have explicit turn limits;
- policy and prior-agent text are always untrusted data;
- required tool evidence, policy and prior role proposals are never silently truncated. Optional
  reviewed memory may be removed; an oversized required context stops safely;
- one validation repair per workflow is shared across Investigator schema errors and Resolution
  schema/reference errors. Feedback includes only the validation error and grounded reference
  registries, never an expected answer. Every invocation is persisted and counted within the same
  call/time/token budget, not a free invisible retry;
- `CaseReasoner` remains available, but a paired single-agent versus multi-role quality/cost
  comparison has not been completed.

The shared integrated runtime currently bounds 16 model calls, 12 tool calls, 8 investigation turns,
3 policy turns, 2 replans, 48,000 total input tokens and 8,000 total output tokens. The 90-second
orchestration deadline is checked at call boundaries, not enforced as an in-flight cancellation.
Provider requests have separately configured timeout/retry bounds.
`RESOLVEOPS_AGENT_MAX_OUTPUT_TOKENS` defaults to 1600 per structured role call; this is separate
from the ordinary single-response Gemini setting, and explicitly lower limits remain honored.
The repair call is included in the 16-call ceiling. Each
evaluation report records its actual token limits rather than assuming defaults never change.
Live development attempts confirmed that the old 800/1,200 per-call and 24,000/4,000 total token
limits could cut off required source-grounded output. These bounded increases preserve full
evidence and fail-closed validation; they do not establish cost efficiency or reliability.
Provider-reported tokens from invalid structured responses are still consumed and reported;
missing usage/pricing stays unknown. Local fixture latency is not a model-provider or deployment SLO.

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
not been applied. A public Render sandbox is distinct from proof of deployed live-model workflow
execution. Authenticated production MCP transport, integrated live-model quality, calibrated human
labels, a single-agent quality/cost comparison and multi-hour soak evidence remain unproven.
See `EVALUATION.md` for the new-intake integration harness and the exact boundary of old live traces.
