# ResolveOps final JD alignment report

This report maps hiring themes to repository evidence at the end of the 17 implementation packets.
“Implemented” below means covered by tests. “Measured” points to a stored artifact. Terraform is a
validated reference, not a deployed environment. All operational data is synthetic.

| Hiring theme | Implementation and source | Tests or measured evidence | Limitation |
| --- | --- | --- | --- |
| Production ownership | Release gates, readiness, migration ordering, rollback, recovery and incident procedures in `docs/DEPLOYMENT.md` and `docs/OPERATIONS_RUNBOOK.md` | Container/Compose CI, Terraform validation, current-head backup restore drill | No real production tenancy or on-call history |
| Multi-agent coordination | Five distinct role prompts, schemas and invocations in `src/resolveops/agents/`; hierarchy in `src/resolveops/orchestration/graph.py` and `src/resolveops/orchestration/domain.py` | 22/22 `evals/agents/latest-report.json`; API and orchestration tests | Offline contract provider; broad live-model quality unmeasured |
| Planning and routing | Supervisor returns typed goals, plan steps, delegations, evidence needs, stop/escalation; global graph routes customer/IT subgraphs | Trajectory accept/replan/escalate cases and graph tests | Planner does not control authorization or writes |
| Tool/function calling | Investigator and Policy choose typed allowlisted reads in bounded loops; `src/resolveops/agents/tools.py` persists safe call telemetry | Malformed inputs, forbidden writes, timeout/error, and trajectory-tool tests | External enterprise tools are simulated |
| Agent Skills | Five concrete skill specifications in `src/resolveops/agents/skills.py` bind roles, schemas, tools, timeouts and policy tags | Skill catalogue/tool permission tests | Deliberately no additional skill framework |
| Context engineering | Per-role builder in `src/resolveops/agents/context.py`; caps, provenance, redaction, freshness and metrics | Context truncation, duplicate, stale, wrong-tenant and injected-content tests | Token count is an estimate when provider usage is absent |
| Memory/state | Typed LangGraph state/checkpoints plus reviewed, expiring, tenant/issue-scoped memory in `src/resolveops/memory/` | Persistence, expiry, policy-version and cross-tenant tests; hierarchical-memory regression | No automatic learning; reviewed memory remains advisory |
| RAG | Versioned policies, chunking, embeddings, BM25/vector hybrid search and citation checks in `src/resolveops/knowledge/` | 50-query retrieval set with Recall@3/MRR/nDCG | Only 17 production-path chunks |
| Hybrid retrieval/reranking | Hybrid baseline and optional FastEmbed cross-encoder experiment | Reranker report: MRR 0.9233→0.9367, nDCG 0.9363→0.9531, p95 ~45.75→1,179.72 ms; rejected | Reranker not used online because latency failed rule |
| MCP | Read-only server plus tenant-bound local MCP consumer with fallback in `src/resolveops/interfaces/` and `src/resolveops/agents/tools.py` | MCP server/client allowlist, tenant mismatch, malformed response and fallback tests | Remote production MCP rejected until authenticated transport exists |
| Backend/FastAPI | Authenticated operations, agent jobs/SSE, audit, feedback, metrics, demo and health routes in `src/resolveops/api/` | API, browser, security and deployment verification tests | Single service by design |
| Python | Python 3.12, Pydantic v2 contracts, strict MyPy, Ruff and pytest | 243 passed, 5 environment-dependent skips at final pre-documentation run | Python 3.14 deliberately rejected for dependency compatibility |
| SQL/PostgreSQL | SQLAlchemy, Alembic through 0018, transactions, row locks, SKIP LOCKED, indexes and database-per-tenant routing | Migration round trip; PostgreSQL persistence/concurrency; 151,862-record scale artifact | Local demo uses SQLite and has weaker process durability |
| Async/concurrency | Parallel specialist branches, SSE async streaming, concurrent workers, PostgreSQL locked claims | 200/200 jobs claimed once across 8 workers; concurrent refund/approval/webhook tests | Provider concurrency and production pool sizing unmeasured |
| Durable workflow | LangGraph checkpoints plus application-owned workflow/job/event tables | Pause/resume, restart state, lease recovery and migration tests | Durable checkpointer requires PostgreSQL |
| HITL | Persisted customer and IT approval requests/decisions with notes and role checks | Browser completes approve/resume; rejection and duplicate-decision tests | No external approval/identity platform |
| Reliability | Idempotency, bounded retry, verify-only recovery, leases, dead letters, event histories | Failure/recovery tests and Reliability UI browser flow | Multi-hour chaos/soak not performed |
| Idempotency | Tenant-scoped operation/job keys and database uniqueness; replay returns existing result | Duplicate actions, events, approvals, IT grants and enqueue tests | External vendor idempotency is simulated |
| Recovery | Explicit verification/recovery graph, expired-lease recovery and operator runbook | Verify-only and worker-recovery tests; current-head restore drill | No cross-region recovery exercise |
| Evals | Separate workflow, trajectory, retrieval, response, live-provider and security runners | Seven manifests / 154 versioned cases | Designed regression evidence, not representative accuracy |
| Gold datasets | Hashed semantic-version manifests with descriptions, labels, categories and creation method | Catalog test rejects hash/count drift | Labels are hand-authored synthetic cases |
| Regression | CI runs workflows, agents, security, tests, typing, Docker/PostgreSQL and Terraform gates | 243 passed / 5 skipped locally before final docs; GitHub result is authoritative after push | Browser/PostgreSQL depend on their environments |
| Offline scoring | Deterministic final-state, citation, route, tool, budget and security assertions | 24/24 customer, 14/14 IT, 22/22 trajectory, 17/17 security | Does not score subjective natural-language quality |
| Online/demo scoring | Optional three-case Gemini gate records structured output, usage and latency | Recorded 3/3 synthetic run, 1,589 provider-reported tokens | Tiny one-time sample; not CI or multi-agent evidence |
| Human judgment | Six-field response rubric and export/import review process | 24 automated candidates; **0/24 human-reviewed** | Owner must supply genuine labels; they are not fabricated |
| Failure taxonomy | Typed failure classes connected to eval reports, case studies and recovery | Genuine generator, index, rate-limit and reranker failures documented | Taxonomy will grow with real incidents |
| Observability | Structured trace events, Prometheus HTTP/agent/tool/queue metrics and optional OTLP/HTTP exporter | Metrics and exporter mapping/fallback tests | No collector/dashboard deployed |
| OpenTelemetry | Completed internal events become OTel spans with status and bounded attributes in `observability/otel.py` | Export configuration, span mapping and safe fallback tests | Export endpoint is optional and unverified against a real backend |
| Latency | Trace summaries and reproducible workflow/API/retrieval/queue benchmarks | Offline workflow p95 34.92 ms; mixed API p95 47 ms; artifacts preserve details | Desktop/offline results are not production SLOs |
| Tokens | Per-run provider usage plus context estimates; budgets in `agents/budgets.py` | Trajectory artifact: 71,991 estimated input tokens across 22 cases | Offline provider has no output/provider-billed usage |
| Cost | Explicit input/output price settings and hard cost budget in `src/resolveops/agents/budgets.py`; `docs/COST_ANALYSIS.md` | Cost logic tests, including unknown-cost behavior | No fabricated monthly or multi-agent dollar total |
| Security | Auth, server-derived identity, RBAC, body/rate limits, HMAC webhooks, secret scan, Bandit and input guards | 17/17 adversarial gate; cross-tenant, PII, webhook, traffic and repository tests | No external penetration test or WAF |
| Tenant isolation | Authenticated tenant selects a separate session factory/database; agents/memory/jobs are scoped | Cross-database records, tools, memory, webhook and job tests | Terraform provisions one tenant database as a reference |
| RBAC | Fixed permission map for reads, PII, approval and action execution | Denial/role tests across APIs and workflows | No enterprise IdP/group lifecycle |
| Prompt injection | Untrusted policy boundary, ingestion rejection, typed citations, no model write tools | Versioned attack/benign gate plus context-security tests | Pattern guard cannot stop every semantic/obfuscated attack |
| CI/CD | Pinned GitHub Actions, OIDC AWS workflow, immutable image SHA, migration gate and ECS circuit breakers | Workflow syntax plus local equivalent gates; Terraform validates | Deployment workflow has not run against an AWS account |
| Docker | Multi-stage non-root image, read-only root, Compose migrations/API/demo/Redis/worker | CI builds/runs image and Compose health check | Local Docker is not cloud availability evidence |
| Cloud | Terraform for ALB, ECS API/worker, RDS, TLS Valkey, ECR, Secrets Manager, alarms and private networking | Terraform 1.10.5 format/init/validate passed in a disposable container | Not applied; can incur charges; default is not multi-AZ |
| Terraform | Version-pinned provider lock, variables/validation, outputs and remote-state workflow | `terraform validate` passed after worker/cache change | No plan against an authenticated account |
| Load tests | Read-only saturation/soak, mixed read/write soak, scale and queue-race runners | 232/232 mixed requests; 200/200 unique claims; 151,862 records | Short local samples, no approval/action capacity curve |
| Feedback/data flywheel | Structured operator correction, review states, export/import promotion boundary | Feedback API/store/UI and dataset lifecycle tests | No automatic prompt update or training |
| Product UX | Neutral operations console with queues, split case workspace, approvals, IT, reliability, audit and dark mode | Chromium completes customer approval/action, IT approval/grant, safety stop and reset | No customer portal or accessibility audit by external users |

## Final claim boundary

The implementation packets are complete in the repository. The remaining steps require external
ownership or genuine human work: rotate the exposed provider key, label the 24 response candidates,
approve repository visibility, optionally record the walkthrough, and optionally authorize a cloud
account and budget. Until those happen, ResolveOps must be described as locally working and
production-minded—not publicly deployed, human-evaluated, or production proven.
