# ResolveOps final architectural upgrade: JD alignment and gap audit

Status: **audit only — implementation is not approved by this document**  
Audit date: 2026-09-29  
Audited revision: `d6a7b89` (`codex-build`)  

This document is the required pre-implementation gate for the proposed transition from two
deterministic LangGraph domain workflows with one bounded advisory reasoner to a production-minded,
hierarchical multi-agent system. It distinguishes existing evidence from proposed work. It does not
claim that planned components exist.

## Executive finding

ResolveOps is currently a strong **agentic workflow application**, but it is **not a true multi-agent
system** under the acceptance criteria in this upgrade specification. It has two explicit LangGraph
workflows, one bounded `CaseReasoner` invocation, typed domain state, policy retrieval, durable
customer approval/checkpointing, deterministic execution, fresh-state verification, audit,
reliability controls, realistic synthetic-data tooling, and measured local performance. It does not
have a global supervisor graph, specialist model roles, autonomous read-tool loops, agent handoffs,
agent-run/tool-call persistence, replanning, independent model critic, reviewed memory, a queue,
SSE, distributed rate limiting, or agent-specific evaluations.

The transition is feasible without replacing the proven control plane. The safest design wraps the
existing customer and IT action/verification paths with a new hierarchical reasoning plane. Model
roles may plan, investigate, retrieve, resolve, and criticize; existing deterministic code continues
to authorize, approve, execute, and verify.

## A. Requirements audit: all 86 sections

Legend: **CURRENT** is implemented and evidenced; **PARTIAL** has reusable implementation but misses
material acceptance criteria; **MISSING** is not implemented; **NOT JUSTIFIED** should remain absent
unless an experiment proves a need.

| # | Requirement | Status | Current evidence and exact gap |
|---:|---|---|---|
| 0 | Architecture/JD gap audit | CURRENT | This document provides the required gate. No runtime modification is included. |
| 1 | Hierarchical orchestration | MISSING | `CustomerIssueWorkflow` and `EmployeeAccessWorkflow` are separate graphs. There is no global intake/supervisor graph, shared recovery graph, or replanning router. |
| 2 | Five real reasoning roles | MISSING | `reasoning/agent.py` contains one bounded `CaseReasoner`. There are no separate Supervisor, Investigation, Policy, Resolution, and Critic model invocations. |
| 3 | Multi-agent acceptance criteria | MISSING | Distinct prompts, outputs, permissions, handoffs, loops, routing, and per-agent telemetry do not exist as a complete set. ResolveOps must not currently be described as multi-agent. |
| 4 | Shared typed agent state | PARTIAL | Both domain graphs use typed state, but there is no common agent state containing plans, handoffs, budgets, critic findings, and provenance. |
| 5 | Agent-run persistence | MISSING | There is no `agent_runs` table or durable per-agent output/usage/error record. Existing reasoning metadata is embedded in a workflow result. |
| 6 | Tool-call persistence | MISSING | Tool spans exist in telemetry, but no durable, tenant-scoped `agent_tool_calls` records exist. |
| 7 | Least-privilege agent tools | PARTIAL | RBAC, masked read tools, deterministic action tools, and a read-only MCP server exist. Models do not yet receive distinct role-specific tool registries. |
| 8 | Deterministic control plane | CURRENT | Authentication, tenant routing, RBAC, Decimal arithmetic, approval, idempotency, writes, and final verification are deterministic and must be preserved. |
| 9 | Bounded autonomous loops | MISSING | Current graphs are bounded fixed paths. The model cannot choose the next read tool or retrieval iteration, and Supervisor replanning does not exist. |
| 10 | Parallel multi-agent execution | MISSING | No parallel specialist or per-issue agent fan-out/join exists. Current multi-issue work is processed through independent fixed workflow calls. |
| 11 | Agent disagreement handling | MISSING | No independent critic exists, so disagreement → replan/retrieve/escalate is not modeled or persisted. |
| 12 | Context engineering | PARTIAL | `ReasoningContext` is typed, scoped, citation-validated, and PII-aware. It lacks role-specific builders, explicit token allocation, freshness rules, truncation records, and context metrics. |
| 13 | Context-quality evaluation | MISSING | Existing security/retrieval tests cover some malicious knowledge and citations, but there is no dedicated context inclusion/exclusion/staleness/size evaluation suite. |
| 14 | Three-level agent memory | PARTIAL | PostgreSQL LangGraph checkpoints provide workflow working state. Structured case data exists. There is no reviewed-resolution memory or promotion rule. |
| 15 | Memory retrieval and ablation | MISSING | No advisory reviewed-pattern retriever and no with-memory/without-memory experiment exist. |
| 16 | Agent Skills | MISSING | Typed domain functions exist, but there is no small declarative skill registry with role, schema, tool, context, timeout, policy, and evaluation metadata. |
| 17 | Real model tool/function calling | PARTIAL | Pydantic tools, errors, idempotency, observability, and authorization exist. The model does not autonomously select/call read tools in a bounded loop. |
| 18 | MCP server and consumer | PARTIAL | `interfaces/mcp_server.py` exposes five read-only tools. ResolveOps does not consume an external MCP evidence service. |
| 19 | Retrieval production path | PARTIAL | Versioned hybrid lexical/vector retrieval and retrieval metrics exist. Online search is in-process; no measured exact-vs-pgvector serving experiment exists. |
| 20 | Reranking experiment | MISSING | Reranking is documented as deferred, but no current hybrid-vs-cross-encoder measurement artifact proves the decision. |
| 21 | Large realistic synthetic data | PARTIAL | Deterministic demo/small/medium/large generators exist for connected customer and IT records. New agent, tool, memory, queue, and richer scenario records are absent. |
| 22 | Labelled scenario generation | PARTIAL | Payment, return, approval, verification, duplicate, and IT labels exist. The required full label catalogue and expected multi-agent trajectories do not. |
| 23 | Data-quality tests | PARTIAL | Generator validation performs 12+ checks including integrity and currency. New agent/memory/tool/queue ordering and cross-tenant checks are absent. |
| 24 | Gold and stress workflow sets | MISSING | Current curated sets total 38 cases (24 customer, 14 IT), below the requested 60–100. There is no separate large generated trajectory stress set. |
| 25 | Trajectory evaluation | MISSING | Existing evaluation scores final workflow behavior and nodes, not specialist routing, tool selection, handoff, replanning, or loop efficiency. |
| 26 | Agent-specific evaluations | MISSING | No role-specific datasets or metrics exist because the roles do not exist. |
| 27 | Single-vs-multi-agent ablation | MISSING | The existing single reasoner can become the baseline, but no multi-agent arm or comparison artifact exists. |
| 28 | Additional ablations | PARTIAL | BM25/vector/hybrid retrieval is measurable. Critic, memory, scoped-context, reranker, parallelism, and per-role model ablations are absent. |
| 29 | Experiment framework | PARTIAL | Dataset manifests and lightweight JSON experiment helpers exist. They do not capture per-agent prompts/models/tools/memory/budgets and git/config metadata together. |
| 30 | Human labels and judge calibration | PARTIAL | CSV export/import and rubric validation exist; no fabricated labels are present. There is no populated human-labelled set or calibrated optional judge. |
| 31 | Feedback/data flywheel | PARTIAL | Structured operator feedback, review states, API, and UI are implemented. Promotion into versioned agent evaluation candidates is incomplete. |
| 32 | Failure taxonomy | PARTIAL | `evals/failure_taxonomy.md`, typed operation errors, and reliability categories exist. New planning/routing/context/model/agent failures are not enforced across every eval. |
| 33 | Trace→failure→fix→regression | PARTIAL | Genuine cases are recorded in `FAILURE_CASES.md` and `FAILURE_ANALYSIS.md`. Multi-agent failures cannot yet be documented. |
| 34 | Production agent budgets | MISSING | Provider input limits and bounded retries exist, but no shared max steps/model calls/tool calls/tokens/wall-clock/cost accounting exists. |
| 35 | Model routing by role | MISSING | Gemini/OpenAI providers are configurable globally. There is no role-to-provider/model map. |
| 36 | Model fallback | PARTIAL | Provider failures fail closed and deterministic execution remains safe. There is no contract-preserving, bounded optional fallback chain. |
| 37 | Model-selection experiments | MISSING | One live Gemini report exists; no controlled role/model comparison should be claimed. |
| 38 | Cost/latency envelope | PARTIAL | Custom spans capture latency and provider usage; performance summaries expose tokens/cost fields. No per-agent budget ledger or multi-agent p50/p95/cost exists. |
| 39 | Standard observability | PARTIAL | Correlated hierarchical custom traces cover HTTP/workflow/node/tool/retrieval/LLM. They are not OpenTelemetry spans and lack agent/handoff components. |
| 40 | Optional OTLP export | MISSING | The sink abstraction can support it, but no OTLP exporter is implemented. |
| 41 | Async/concurrent production path | MISSING | API and workflows are largely synchronous. Only middleware/webhook boundaries are async; no measured controlled model/tool concurrency exists. |
| 42 | Background worker/queue | MISSING | Long workflows execute inside API requests. No Redis queue, worker ownership, status job, or failed-job lifecycle exists. |
| 43 | Distributed rate limiting | MISSING | `TokenBucketRateLimiter` is process-local and documented as such. No shared Redis limiter exists. |
| 44 | Backpressure | MISSING | Request limits and action leases exist, but no queue depth, worker concurrency, model quota, dead-job, or backlog health control exists. |
| 45 | SSE workflow events | MISSING | Durable workflow events and polling APIs exist. There is no SSE stream or agent-step live UI. |
| 46 | Human in the loop | PARTIAL | Customer approval is durable pause/resume with reason; IT approval is persisted and audited. Timeout/escalation and safe editable intent are incomplete. |
| 47 | Reliability | PARTIAL | Timeouts, retries, backoff, leases, idempotency, verification, recovery plans, and manual review are strong. Agent replanning and worker recovery do not exist. |
| 48 | Verify-only recovery | CURRENT | Existing action code reads fresh state and avoids blind write replay after uncertain completion. This must remain a flagship invariant. |
| 49 | Concurrency testing | PARTIAL | PostgreSQL tests cover logical side-effect/approval/event races. Queue worker claim races cannot be tested until a queue exists. |
| 50 | Prompt-injection security | PARTIAL | Six malicious-policy classes, typed outputs, citation validation, and untrusted-policy instructions exist. Direct agent-loop/tool-injection/system-extraction suites are absent. |
| 51 | Tool control | PARTIAL | Typed authorization prevents model-controlled writes and MCP is read-only. Agent allowlist enforcement and forbidden model-call trajectory tests are absent. |
| 52 | Tenancy/PII | CURRENT for present tables | Database-per-tenant routing, masked agent reads, RBAC, webhook verification, secret hygiene, and audit exist. Every new table/interface needs equivalent negative tests. |
| 53 | Resource abuse | PARTIAL | HTTP size/rate bounds and provider input bounds exist. Agent loop, token, tool-spam, queue, and workflow-flood budgets are absent. |
| 54 | Realistic scale test | PARTIAL | A measured PostgreSQL run reached 151,862 records (10,000 customer cases, 2,500 IT cases), not one million. Agent/worker/retrieval-at-corpus-scale measurements are absent. |
| 55 | Query plan/index analysis | CURRENT for case queue | A real before/after case queue index changed measured p95 from 7.455 ms to 4.090 ms. New agent/queue queries will require fresh plans. |
| 56 | Load testing | PARTIAL | A reproducible mixed read load script and measured saturation artifact exist. The requested mutation, workflow, queue, and model traffic mix is absent. |
| 57 | Soak testing | PARTIAL | A truthful 60.578-second paced read-only soak exists with 90 requests and zero errors. It is not a long agent/worker soak. |
| 58 | Dataset versioning | CURRENT for existing evals | Manifests include ID, version, source, method, categories, labels, count, checksum, and date. New datasets must use the same contract. |
| 59 | Release gates | PARTIAL | CI has quality, security, PostgreSQL, browser, container, and Terraform jobs. Multi-agent eval subsets, forbidden-action trajectory gate, and full scheduled experiments are absent. |
| 60 | Production-like UI | CURRENT for present product | The console is a restrained light operations UI with optional dark mode, compact tables, split panes, drawers, and genuine state. Agent trace additions must preserve it. |
| 61 | Operations-first navigation | CURRENT | Cases, Approvals, IT Requests, Reliability, and Audit are primary; Cases opens to a populated queue; complaint intake is `+ New case`. |
| 62 | Flagship case workspace | PARTIAL | The current workspace shows context, workflow, evidence, policy, action, verification, and audit. It lacks explicit Supervisor/Investigator/Policy/Resolution/Critic lanes. |
| 63 | Multi-agent trace UX | MISSING | No per-agent duration/model/token/tool/outcome/handoff API or expandable UI exists. |
| 64 | Approval UX | PARTIAL | Action, amount/resource, case, evidence, policy, note, and approve/reject are shown. Agent recommendation, critic result, and gate summary must be added. |
| 65 | Reliability UX | PARTIAL | Real operations, retries, failures, recovery state, p50/p95, and drill-down exist. Agent/model/tool/queue failure dimensions and trace links are incomplete. |
| 66 | Audit UX | CURRENT for present events | Searchable global events include actor, workflow/case, action, result, trace, and filtering. Agent/handoff events do not yet exist. |
| 67 | Operator feedback UX | CURRENT for current categories | Structured feedback is persisted and reviewable. New agent-specific correction categories and promotion lineage are needed. |
| 68 | Browser E2E | PARTIAL | Playwright covers complaint, approval, verified customer outcome, IT success, MFA safety stop, and reset. It cannot cover the absent five-agent timeline. |
| 69 | Public demo | PARTIAL | A restricted, resettable synthetic local demo exists with safe writes and rate limiting. There is no actually deployed public URL; none must be claimed. |
| 70 | Cloud/infra | PARTIAL | AWS Terraform validates network, private RDS, ECS, secrets, logs, alarms, migration task, health checks, and deployment workflow. No paid deployment has occurred; Redis/worker are absent. |
| 71 | Runbook/SLO | PARTIAL | Deployment, reliability, backup, and continuation docs exist. Queue/worker/provider/backlog runbooks and separate target-vs-measured SLOs are incomplete. |
| 72 | Backup/restore | CURRENT | A PostgreSQL backup→mutate→restore→validate drill is implemented and previously measured. New tables must be covered. |
| 73 | Architecture documentation | PARTIAL | README diagrams cover current UI/API/workflow/tools/Postgres path. They do not show queue, worker, supervisor, specialist agents, Redis, or OTLP. |
| 74 | Multi-agent sequence diagram | MISSING | Current diagrams show the deterministic flow, not a five-role sequence. |
| 75 | ADRs | PARTIAL | Six focused ADRs cover advisory reasoning, multi-issue cases, tenancy, retrieval, UI/service, and durability. Multi-agent, memory, context, queue, and MCP-consumer decisions are absent. |
| 76 | Engineering notes | PARTIAL | Real Python, Decimal, payment semantics, multi-issue, retrieval, and reliability history exists. The single→multi-agent transition and experiments do not yet exist. |
| 77 | Failure case studies | CURRENT for current architecture | Genuine symptom/expected/observed/root-cause/fix/regression examples exist. Multi-agent cases must only be added after real failures. |
| 78 | Cost analysis | MISSING for target | Token usage can be collected, but actual five-role calls/tokens/cost do not exist. No production bill is claimed. |
| 79 | Limitations | CURRENT for present architecture | Synthetic integrations, local evidence, cloud status, and scale caveats are explicit. Target limitations must add multi-agent/provider/queue facts. |
| 80 | Recruiter README | PARTIAL | README quickly explains problem, controls, run path, architecture, evidence, and limitations. It lacks live demo/video links and cannot yet claim multi-agent. |
| 81 | Recruiter demo | PARTIAL | Current customer/IT demo is complete. A 60–90 second multi-agent trace story and recorded walkthrough do not exist. |
| 82 | Final JD alignment report | MISSING | Must be created only after implementation and measured verification. |
| 83 | Avoid checkbox architecture | CURRENT as policy | Kubernetes, Kafka, GraphRAG, fine-tuning, extra vector DBs/frameworks, and microservices remain unjustified. Redis is justified only by the queue/shared-coordination requirements. |
| 84 | Human code standard | PARTIAL | Concrete domain names, strict typing, linting, code audit, and no secret policy exist. Large modules and all new abstractions require packet-level review. |
| 85 | Git/delivery method | CURRENT as required process | Existing history is preserved. Each approved packet must be tested, inspected, measured where applicable, committed naturally, and leave a clean tree. |
| 86 | Claim discipline | CURRENT as policy | Current docs distinguish local/synthetic/measured/deployable/deployed. “Multi-agent” remains prohibited until the full acceptance gate passes. |

## B. Why the current system is not true multi-agent

1. A single `CaseReasoner` receives already assembled evidence and policy excerpts.
2. The model makes one structured advisory assessment; it does not plan or select read tools.
3. Customer and IT LangGraph nodes are deterministic workflow steps, not independent reasoning roles.
4. There is no supervisor-to-specialist structured delegation or handoff.
5. There is no autonomous observe→tool→observe loop.
6. There is no separate Resolution model call and no independent Critic model call.
7. There is no agent disagreement/replanning path.
8. There is no shared cross-domain agent state or global domain router.
9. There are no durable per-agent runs or tool-call records.
10. Observability cannot report role-specific tokens, latency, tools, handoffs, or outcomes.
11. Evaluations do not score plans, routes, tool choices, handoffs, or agent-specific failure modes.
12. No per-role model configuration, fallback, budget ledger, memory, queue, or agent event stream exists.

Renaming existing graph nodes would not satisfy these gaps and is explicitly rejected.

## C. Proposed final architecture

```text
Browser console
  |  REST commands + SSE status (no hidden chain-of-thought)
  v
FastAPI: auth / tenant / RBAC / request limits / idempotent submission
  |
  +--> PostgreSQL: cases, approvals, workflow state, agent runs, tool calls,
  |                memory, feedback, audit, queue/job facts
  |
  +--> Redis: bounded job queue, worker coordination, distributed rate limits,
             transient SSE fan-out (PostgreSQL remains durable truth)
  |
  v
Worker --> durable LangGraph Global Supervisor
             |
             +--> Supervisor/Planner (planning and routing only)
             |       |
             |       +--> Customer Operations subgraph
             |       |      +--> Investigation agent read-tool loop
             |       |      +--> Policy agent retrieval loop
             |       |      +--> Resolution agent
             |       |      +--> Independent Critic
             |       |
             |       +--> Employee/IT subgraph
             |              +--> Investigation agent read-tool loop
             |              +--> Policy agent retrieval loop
             |              +--> Resolution agent
             |              +--> Independent Critic
             |
             +--> disagreement/replan (bounded)
             +--> deterministic safety gate
             +--> durable human approval
             +--> existing typed/idempotent executor
             +--> recovery/verification subgraph
                       +--> fresh deterministic reads/invariants
                       +--> separate read-only Critic/Verifier invocation
                       +--> verify-only recovery or manual escalation

LLM providers: configurable per role; same provider/model is a valid default
Knowledge: current versioned hybrid retrieval; pgvector/reranker only if experiments justify
MCP: current read-only server + one isolated read-only simulator consumer
Telemetry: durable safe summaries + current Prometheus + optional OpenTelemetry/OTLP
```

Authority boundary:

```text
agents recommend and challenge
        -> deterministic software authorizes
        -> human approves when required
        -> typed executor writes once
        -> fresh state is read
        -> deterministic invariants + independent verifier determine completion
```

## D. Existing components to reuse

- `workflows/customer_issue.py`, `employee_it/workflow.py`: proven domain rules, routing outcomes,
  approval/action/verification semantics; refactor into callable domain subgraphs rather than replace.
- `workflows/lifecycle.py` and PostgreSQL LangGraph checkpointing: durable run, approval, events,
  resume, and replay behavior.
- `operations/reads.py`, `employee_it/store.py`: source for allowlisted read-only investigation tools.
- `operations/actions.py`, `employee_it/actions.py`: deterministic executor, leases, retries,
  idempotency, verification, and audit boundary.
- `knowledge/*`: versioned documents, safe ingestion, embeddings, lexical/vector/hybrid retrieval,
  citations, and evaluation metrics.
- `reasoning/providers.py`, Gemini/OpenAI providers: structured provider contracts, timeouts, token
  reporting, and safe errors; extend rather than duplicate.
- `observability/*`: correlation context, trace sink interface, Prometheus metrics, benchmarks.
- `security/*`: auth, tenant routing, RBAC, masking, webhook validation, content guard, traffic bounds.
- `feedback/*`, response human-review utilities, evaluation manifests, and experiment JSON artifacts.
- `data_generation/*`, load/scale scripts, Playwright suite, CI, Docker, Terraform, and backup drill.
- Existing operations-first console and API contracts wherever behavior remains compatible.

## E. Modules/files to add

Names are concrete and may be adjusted during the packet diff review; no generic `Manager` or
`Engine` abstraction is proposed.

```text
src/resolveops/agents/
  models.py                 shared typed state, plans, handoffs, budgets, role outputs
  context.py                role-specific, tenant-safe context builders
  prompts.py                versioned role prompts
  registry.py               role-to-provider/model and tool allowlists
  supervisor.py             plan/replan/stop structured invocation
  investigation.py          bounded read-tool loop
  policy_research.py        bounded retrieval loop
  resolution.py             evidence-and-policy proposal
  critic.py                 pre/post independent verification
  tools.py                  typed read-tool protocol and role registries
  skills.py                 small declarative skill catalogue
  persistence.py            agent-run/tool-call/context-usage storage
  budgets.py                shared budget ledger and safe stop

src/resolveops/orchestration/
  state.py                  shared hierarchical graph state
  graph.py                  global intake/supervisor router
  customer.py               customer domain subgraph adapter
  employee_it.py            IT domain subgraph adapter
  recovery.py               explicit verify-only recovery subgraph
  events.py                 safe public workflow event projection

src/resolveops/memory/
  models.py
  store.py                  reviewed, tenant-scoped resolution patterns
  retrieval.py              advisory pattern retrieval

src/resolveops/jobs/
  models.py
  queue.py                  interface + local test implementation
  redis_queue.py            deployable bounded queue
  worker.py                 idempotent workflow runner
  status.py                 job/backpressure health

src/resolveops/interfaces/mcp_client.py
src/resolveops/api/agent_runs.py
src/resolveops/api/stream.py
src/resolveops/observability/otel.py

evals/agents/*              curated role and trajectory sets
evals/context/*             context-quality cases
evals/stress/*              manifests/generator configuration, not huge generated output
evals/ablations/*           reproducible experiment specs/results
scripts/run_agent_evaluation.py
scripts/run_multi_agent_ablation.py
scripts/run_retrieval_experiment.py
scripts/run_worker_soak.py

docs/adr/ADR-007-multi-agent-control-boundary.md
docs/adr/ADR-008-hierarchical-orchestration.md
docs/adr/ADR-009-context-and-memory.md
docs/adr/ADR-010-queue-and-coordination.md
docs/adr/ADR-011-mcp-consumer-boundary.md
docs/MULTI_AGENT_ARCHITECTURE.md
docs/MULTI_AGENT_SEQUENCE.md
docs/AGENT_EVALUATION.md
docs/QUEUE_RUNBOOK.md
docs/SLO.md
docs/RECRUITER_DEMO.md
docs/JD_ALIGNMENT_REPORT.md             created only at final verification
```

## F. Existing code requiring careful refactor

1. `api/operations.py`: submit work asynchronously while preserving current synchronous behavior
   behind an explicit development compatibility setting during migration.
2. `workflows/customer_issue.py`: isolate proven deterministic domain/action/verification segments
   from evidence assembly so the customer subgraph can call them without copying rules.
3. `employee_it/workflow.py`: same separation for eligibility, access action, and verification.
4. `reasoning/agent.py`: retain as the single-reasoner baseline; do not mutate it into five classes.
5. `workflows/state.py` and `employee_it/workflow_state.py`: adapt into domain slices of shared state.
6. `observability/models.py`: add agent, handoff, context, queue, and critic components while keeping
   current trace consumers compatible.
7. `security/traffic.py`: introduce a limiter protocol and Redis implementation; retain local fallback.
8. `api/main.py` and config: queue/provider/role/OTLP wiring with safe production validation.
9. Operator console JS/HTML/CSS: add SSE and structured trace panels without replacing the UI stack.
10. Docker Compose, Terraform, and CI: add worker/Redis and new gates only after the runtime is proven.

No current action authorization, approval threshold, financial arithmetic, idempotency key, tenant
router, or verification invariant should be rewritten merely to fit the agent design.

## G. Database migrations

Use separate reversible migrations so a runtime packet can be rolled back independently.

1. **0016 agent execution records**
   - `agent_runs`: tenant/workflow/role/parent, prompt/schema versions, provider/model, timestamps,
     status, latency, safe context hash, structured output JSON, usage, tool count, error category,
     trace ID.
   - `agent_tool_calls`: run, tool, timestamps, status, latency, hashed/masked argument metadata,
     result category, error category.
   - indexes: `(workflow_id, started_at)`, `(tenant_id, agent_role, started_at)`, run foreign key.
2. **0017 agent context and disagreement**
   - context usage/provenance metrics and persisted disagreements/replan reasons.
3. **0018 reviewed resolution memory**
   - tenant-scoped verified patterns, policy versions, approved resolution, verification outcome,
     feedback linkage, expiry/version/review state; no arbitrary raw model history.
4. **0019 workflow jobs**
   - durable job identity/status/attempt/dead-letter summary/lease timestamps/idempotency key. Redis
     transports jobs but PostgreSQL retains durable business status.
5. Extend feedback lineage and audit event enums only where the existing JSON/event model cannot
   represent agent corrections or promotions.

All migrations require upgrade/downgrade, metadata-drift, backup/restore, tenant-negative, and
existing-data compatibility tests. Structured outputs must be size bounded and must not contain raw
secrets or unnecessary PII.

## H. Proposed dependencies and justification

| Dependency | Placement | Why | Decision rule |
|---|---|---|---|
| `redis>=5,<6` | optional `worker` extra, then deployable runtime | Shared queue, coordination, rate-limit state, and transient event fan-out | Required for the target multi-instance path; local fallback remains available. |
| `arq>=0.26,<1` | optional `worker` extra | Small asyncio Redis worker with retry/job-result primitives; avoids building a queue framework | Adopt only after a spike proves leases, idempotency, bounded retries, and health needs are met. |
| OpenTelemetry API/SDK + OTLP exporter | optional `otel` extra | Standard span export without requiring a hosted vendor | Keep optional; core operation must not depend on an exporter. |
| `pgvector` | optional `experiments` extra | Run the required PostgreSQL retrieval comparison | Do not move serving until measured quality/latency/operations justify it. |
| A cross-encoder package/model | optional experiment environment only | Execute the required reranking experiment | Do not add to runtime/lock by default unless measured gain is meaningful. |

The existing `langgraph`, `mcp`, OpenAI/Gemini, FastAPI, SQLAlchemy, PostgreSQL, Playwright, and
Prometheus dependencies are reused. Do not add CrewAI, AutoGen, another agent framework, Kafka,
Kubernetes, GraphRAG, or another vector database.

Expected dependency risk: Redis/worker is medium-high operational risk; OTEL is medium; pgvector and
reranking are experimental and low runtime risk while isolated.

## I. Evaluation and data changes

1. Grow the curated gold set from 38 to 60–100 genuinely reviewed cases, prioritizing combined
   issues, contradictions, missing evidence, policy conflicts, tool/provider failure, critic
   disagreement, replan, budget stop, cross-tenant denial, and verify-only recovery.
2. Generate hundreds/thousands of labelled stress variations separately; never label these human
   gold. Store generator seed/profile/manifest/checksum, not huge output.
3. Add trajectory observations: route, ordered roles, tool calls, missing/unnecessary calls,
   handoffs, replans, citations, disagreement, stop reason, unauthorized attempts, final invariant.
4. Add role-specific scoring and context-quality suites.
5. Preserve `CaseReasoner` as the single-agent baseline and run multi-agent, critic, memory, context,
   retrieval, reranker, parallelism, and model ablations where resources permit.
6. Extend experiment metadata with git SHA, dataset, role models, prompts, tool schema, retrieval,
   memory, budget, usage, latency, and cost configuration.
7. Use operator review export/import for actual human labels. Do not add an LLM judge until enough
   real labels permit calibration.
8. Add failure-category aggregation and enforce zero unauthorized sensitive executions.
9. Re-run progressive PostgreSQL scale, realistic mixed load, worker concurrency, and a truthful
   bounded soak. Existing 151,862-row and 60.578-second results remain historical baselines.

## J. UI changes

- Keep the current light, compact operations design and navigation.
- Replace request-blocking execution with run submission and a visible durable status.
- Add SSE-driven timeline events: Supervisor, Investigator, tool/evidence, Policy, Resolution,
  Critic, safety gate, approval, executor, verification/recovery.
- Never expose chain-of-thought, full prompts, raw hidden context, secrets, or unnecessary PII.
- Add an expandable technical trace row: role, duration, provider/model, input/output token counts,
  tool count/names, outcome, handoff, safe structured output.
- Extend approval detail with recommendation, critic result, deterministic gate, evidence/policy,
  requested time, action/amount/resource, and reason.
- Extend Reliability with agent/model/tool/queue failures, budget stops, recovery events, and trace
  links; extend Audit with agent/handoff actors.
- Add agent-specific feedback reasons while retaining existing structured review flow.
- Preserve customer and IT end-to-end workflows and mobile behavior.

## K. Reliability and security changes

- A shared budget ledger enforces steps, model calls, tool calls, tokens, wall clock, retries, and an
  optional configured cost ceiling.
- Every role has a fixed tool allowlist. Supervisor/Resolution have no side-effect tools;
  Investigation/Policy/Critic have read-only tools. Only the existing executor writes.
- Structured provider output and tool input are Pydantic validated; unknown tools and malformed
  arguments fail before execution.
- Context builders enforce tenant, masking, freshness, size, provenance, and untrusted-content rules.
- Critic rejection blocks execution and produces a durable replan/escalation reason.
- Provider fallback is bounded, schema-compatible, visible, and cannot change safety rules.
- Queue submissions and workers are idempotent; PostgreSQL status plus leases prevent double work.
- Backpressure includes queue capacity, concurrency, timeout, retry, dead-job, and quota health.
- Redis coordination is namespaced and credential protected; no sensitive payload is required in
  transient Redis messages.
- Add direct/indirect injection, tool-instruction, prompt-extraction, forbidden-tool, cross-tenant,
  budget exhaustion, tool spam, duplicate worker, and state-corruption tests.
- Preserve verify-only recovery: uncertain response never causes blind financial/access replay.

## L. Deployment changes

- Development: API + PostgreSQL may run synchronously/local-queue for fast tests; a Compose profile
  runs Redis + worker for production-like behavior.
- Deployable AWS reference: add ElastiCache/Redis networking and security, ECS worker service,
  worker autoscaling/alarms, queue/backlog/dead-job metrics, and secrets. Keep RDS private.
- Deploy workflow: migrate first, deploy worker in compatibility mode, deploy API, enable queued
  submissions only after health checks; rollback feature flag before reverting services.
- Public demo: choose a free/cheap host only with explicit owner approval, synthetic tenant, reset,
  strict rates/budgets, no pasted provider key, and restricted actions. Until a URL is actually
  running, documentation says local demo/deployable infrastructure—not deployed.
- Optional OTLP endpoint is environment configured and non-blocking.
- Update start/stop/deploy/migrate/rollback/worker/Redis/provider/backlog/stuck-job/secret/backup
  runbooks and keep measurable SLO targets separate from results.

## M. Implementation packets in dependency order

Each packet follows: explain → implement → targeted tests → broader tests → inspect/simplify →
benchmark/eval when relevant → natural commit → clean tree.

| Packet | Scope and exit evidence | Risk |
|---:|---|---|
| 1 | Freeze contracts and baselines: architecture tests, current eval/load artifacts, compatibility API tests, ADR for control boundary | Low |
| 2 | Agent contracts: shared typed state, five role outputs, context/budget models, prompt/schema versions, no runtime routing yet | Medium |
| 3 | Persistence migration 0016/0017: agent runs, tool calls, context metrics, disagreement; tenant/security/migration tests | High |
| 4 | Least-privilege read tools and skill catalogue: Pydantic schemas, allowlists, timeout/error contracts, forbidden-write tests | High |
| 5 | Role invocations: Supervisor, Investigation loop, Policy loop, Resolution, independent Critic; separate prompts/traces/usage | High |
| 6 | Hierarchical LangGraph: global router, customer/IT subgraph adapters, bounded replan/disagreement and explicit recovery graph | Very high |
| 7 | Deterministic integration: preserve approval, executor, idempotency, fresh verification, verify-only recovery; Postgres concurrency suite | Very high |
| 8 | Context and reviewed memory: migration 0018, promotion/retrieval, contamination tests, memory/context ablations | High |
| 9 | MCP consumer: one isolated read-only external simulator interface, failure fallback, tenant/tool security tests | Medium |
| 10 | Evaluation expansion: gold/stress/trajectory/role suites, failure taxonomy, single-vs-multi and critic/parallel/context experiments | High |
| 11 | Retrieval experiments: scaled exact-vs-pgvector and hybrid-vs-reranker; adopt only measured winners | Medium |
| 12 | Queue and coordination: migration 0019, Redis/worker, idempotent claims, backpressure, shared limiter, compatibility flag | Very high |
| 13 | SSE and console: durable event projection, agent trace/approval/reliability/audit/feedback UI, complete Playwright flows | High |
| 14 | Standard observability: OpenTelemetry mapping, optional OTLP, role/tool/queue metrics, budget and cost envelopes | Medium |
| 15 | Scale/load/soak/security: progressive data, mixed mutation load, multi-worker races, bounded soak, injection/abuse gates | High |
| 16 | Deployment and operations: Compose, Terraform worker/Redis, rollout/rollback, runbooks/SLO, backup drill covering new tables | High |
| 17 | Recruiter evidence and final audit: README, architecture/sequence, 90-second script, limitations, measured costs, final JD report | Medium |

Packets 1–7 establish truthful multi-agent behavior. Packets 8–17 complete the full production-minded
specification. No “multi-agent” claim is allowed before Packet 7 plus acceptance tests; no
“production scale” or “deployed” claim is allowed without the relevant measured/deployed evidence.

## N. Risk summary

- **Very high:** hierarchical graph integration, preservation of pause/resume checkpoints,
  deterministic action boundary, queue cutover, and multi-worker idempotency.
- **High:** new persistence with PII-safe outputs, autonomous tool loops, context isolation, memory
  contamination, evaluation validity, SSE reconnection/order, and Terraform Redis/worker changes.
- **Medium:** provider routing/fallback, optional OTEL, MCP consumer, retrieval experiments, console
  trace presentation, documentation and recruiter material.
- **Low:** contract freeze, additional manifests, static diagrams, and compatibility fixtures.

Primary architectural risks:

1. More model calls increase latency, token use, provider failure surface, and cost.
2. Autonomous tool selection can produce useless loops or miss mandatory evidence.
3. Concurrency can duplicate work unless workflow/job/action idempotency remains separate and clear.
4. Persisted structured outputs can leak PII or grow without bounds.
5. Agent disagreement can loop; budgets and explicit escalation are mandatory.
6. Memory can transfer a prior resolution incorrectly; only reviewed, scoped, expiring patterns are
   eligible and they remain advisory.
7. Refactoring proven workflows can regress approval/recovery; compatibility and shadow comparisons
   precede cutover.
8. Redis adds a new failure mode; PostgreSQL remains the business source of truth and local fallback
   remains available.

## O. Deliberate non-implementations

- Kubernetes, Kafka, microservices, GraphRAG, fine-tuning, another vector database, or another agent
  framework.
- More than the five justified reasoning roles unless measured failures prove a missing boundary.
- Model-issued sensitive writes, model approval, model-defined arithmetic, or model-defined final
  completion.
- Giant raw chat history as state, unreviewed long-term memory, automatic prompt/training updates,
  uncalibrated LLM judge as truth, or chain-of-thought storage/display.
- Runtime pgvector or reranking unless the experiments show meaningful benefit.
- Paid cloud resources or public deployment without owner approval.
- Fake scale, human-review, cost, availability, deployment, or multi-agent claims.
- A frontend framework rewrite; the current interface can support the required trace UX.

## P. Expected latency, token, and cost increase

No target measurement exists yet, so only call-count arithmetic and planning ranges are stated.

- Current reasoning path: normally zero or one advisory model invocation per issue.
- Proposed straightforward path: Supervisor + Investigation + Policy + Resolution + pre-execution
  Critic + post-execution Critic = approximately **6 minimum role invocations**, with additional
  Investigation/Policy loop turns and at most bounded replans.
- Multi-issue requests may fan out investigations. Parallel execution can reduce elapsed latency but
  does not reduce token/cost totals.
- A reasonable initial hard cap for experiment design is 10 model calls, 16 read-tool calls, two
  replans, and one pre/post critic pair per workflow; final values must be tuned from measured data.
- Compared with one advisory call, model latency and token cost will likely rise several-fold. Exact
  p50/p95, tokens, and USD estimates must be produced from provider usage and configured pricing
  during Packets 5/10/14. No dollar figure is claimed now.
- The ablation must prove that better missing-evidence, unsafe-action, citation, or escalation results
  justify this cost. If it does not, retain the simpler reasoner as the default and document the
  multi-agent experiment honestly.

## Q. Backward-compatibility strategy

1. Keep current API response fields; add run IDs, agent state, and event links additively.
2. Retain `CaseReasoner` and current workflows as a baseline/compatibility runtime.
3. Add `RESOLVEOPS_ORCHESTRATION_MODE=single|multi` with `single` default until shadow/eval and
   migration gates pass; production validation makes the choice explicit.
4. New database columns/tables are additive before code depends on them.
5. Queue submission uses an idempotency key derived from the existing workflow request identity.
6. Existing approval IDs, workflow IDs, action keys, audit records, and checkpoint thread IDs remain
   stable.
7. Existing console continues polling if SSE is unavailable; SSE is an additive enhancement.
8. Old completed workflows remain readable without backfilling fabricated agent runs.
9. Existing local demo remains usable without Redis/model credentials through deterministic/single
   mode; the multi-agent demo reports configuration absence honestly.

## R. Rollback strategy

- Every high-risk feature is protected by explicit configuration and can return to `single` mode.
- Deploy additive migrations first; code rollback does not require immediately dropping tables.
- Disable new submission, drain/stop workers, and leave durable in-flight jobs visible before API
  rollback.
- An in-flight multi-agent workflow is either resumed by the compatible worker version or escalated;
  it is never silently re-executed through the old action path.
- Redis loss pauses new distributed work; PostgreSQL job/workflow/action truth supports recovery.
- Revert SSE to polling without changing business state.
- Retrieval/memory/reranker/OTLP/MCP-consumer features have independent flags and fail closed or fall
  back to the proven local components.
- Destructive migration downgrades occur only after backup, compatibility verification, and proof no
  retained records are needed. Normal rollback leaves additive tables intact.
- Run the existing backup/restore drill plus new table validation before release cutover.

## S. Definition of Done

The complete modification is done only when all statements below are true and evidenced:

1. A global durable LangGraph routes typed work to customer/IT subgraphs and explicit recovery.
2. Five justified roles have distinct prompts, invocations, outputs, permissions, traces, usage, and
   agent-specific tests.
3. Investigation and Policy use bounded autonomous read-tool/retrieval loops; Supervisor performs
   bounded plan/replan; multi-issue parallelism is measured.
4. Structured state and handoffs are checkpointed; agent/tool/context/disagreement records are
   durable, tenant safe, size bounded, masked, and migrated.
5. Resolution/Critic disagreement blocks execution and safely replans or escalates.
6. Deterministic RBAC, tenancy, approval, arithmetic, limits, idempotency, writes, and final
   invariants remain authoritative.
7. Verify-only recovery and all existing customer/IT end-to-end paths pass regression and PostgreSQL
   concurrency tests.
8. Reviewed memory is scoped, expiring, advisory, promotable only after review, and ablated.
9. ResolveOps both exposes read-only MCP tools and consumes one meaningful read-only MCP evidence
   service without moving writes outside the control plane.
10. Gold, stress, trajectory, role, context, security, and ablation datasets have versioned manifests
    and reproducible reports; synthetic labels are never called human labels.
11. The single-vs-multi ablation reports correctness, safety, citations, escalation, latency, tokens,
    calls, tools, and configured cost honestly.
12. Redis worker/queue, shared limiter, backpressure, failed-job handling, health, and multi-worker
    idempotency are proven; synchronous/local compatibility remains documented.
13. SSE and console show safe structured agent/tool/policy/approval/action/verification events and
    per-agent telemetry without chain-of-thought.
14. Custom traces map to optional OpenTelemetry export; failures never break business execution.
15. Full lint, format, strict type, unit, integration, PostgreSQL, browser, security, container,
    Terraform, migration, eval, and forbidden-action gates pass in CI at the final revision.
16. Progressive scale, mixed load, query plans, and bounded soak produce stored truthful artifacts
    with hardware/environment/limitations.
17. Docker/deployable AWS/runbook/SLO/backup/rollback documentation includes worker/Redis/provider
    failures; no paid deployment occurs without approval.
18. README, architecture, sequence, recruiter demo, engineering notes, limitations, cost analysis,
    failure cases, and `JD_ALIGNMENT_REPORT.md` cite exact code/tests/measurements.
19. Working tree is clean, commits are coherent, no secrets exist, and historical commits are not
    rewritten.
20. Only then may the repository call ResolveOps a true multi-agent system. “Deployed,” “production
    scale,” and “human evaluated” remain restricted to separately proven facts.

## Approval gate

This audit intentionally makes no runtime change. Approval should confirm three choices before
Packet 1 begins:

1. accept a real architectural expansion with Redis/worker as an optional production profile;
2. accept materially higher model latency/token usage subject to a measured ablation and permission
   to keep the simpler mode if multi-agent does not earn its cost;
3. keep paid cloud deployment outside scope until separately authorized.

