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

These controls reduce avoidable usage without weakening the deterministic safety boundary. A
multi-agent path will still cost more than one advisory call; measured ablation must determine when
that cost earns better outcomes.

## Persistence

Migration `0016_agent_execution_records` adds `agent_runs` and `agent_tool_calls`. Migration
`0017_reviewed_resolution_memory` adds tenant-scoped, expiring memory that can contain only reviewed
resolution patterns. Raw arguments, secrets and arbitrary model histories are not memory.

## Current limitation

The guarded multi-agent path currently runs in the API process. Redis-backed background execution,
SSE delivery, role-specific gold evaluations, retrieval/reranking experiments, public hosting and
cloud worker deployment remain planned work and must not be claimed as implemented.
