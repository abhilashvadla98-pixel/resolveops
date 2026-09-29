# ResolveOps

ResolveOps investigates operations cases across simulated enterprise systems. It currently includes
Customer Operations and Employee/IT domain packs. The first models customers, orders, payments,
returns, refunds, and independently tracked case issues. The second models employee identity,
team membership, directory groups, repository access, approvals, tickets, and notifications.

This repository does not connect to real payment, CRM, directory, Git, or support platforms.

## Local setup

ResolveOps uses Python 3.12.

```powershell
python -m pip install "uv==0.12.20"
uv sync --locked --all-extras
```

`uv.lock` is the single dependency lock for local work, CI, and the application image. Run
`uv lock --check` after changing `pyproject.toml`; update the lock intentionally with `uv lock`.

Copy `.env.example` to `.env` and replace the example PostgreSQL password with the password for
your local development database. `.env` is ignored by Git.

Create or update the database schema:

```powershell
.\.venv\Scripts\alembic.exe upgrade head
```

Load the repeatable Customer Operations and Employee/IT samples:

```powershell
.\.venv\Scripts\python.exe -m resolveops.database.seed
```

The sample contains one customer case with a possible duplicate charge and a missing return refund,
plus an approved ML Platform repository-access case whose group and repository grants are missing.

## Policy knowledge and retrieval

Versioned Markdown policies live under each domain pack's `policies` directory. Every document
has validated TOML metadata for its identity, version, status, applicable issue types, source, and
effective date. Ingestion uses heading-aware chunks, immutable content fingerprints, and separate
embedding records so a later model can be added without rewriting the source documents.

After running migrations, build the local semantic index with FastEmbed:

```powershell
.\.venv\Scripts\python.exe -m resolveops.knowledge.cli --provider fastembed
```

The first run downloads `BAAI/bge-small-en-v1.5`; no paid API key is required. For fully offline
development and deterministic tests, use `--provider feature-hash`. Retrieval returns the policy
version, section, source, effective dates, chunk text, and ranking evidence.

The retrieval layer provides exact cosine vector search, Okapi BM25 lexical search, and weighted
reciprocal-rank fusion. Reproduce the checked-in 50-question evaluation with:

```powershell
.\.venv\Scripts\python.exe -m resolveops.knowledge.evaluate --provider fastembed --k 3
```

The command safely re-runs ingestion and reports document-level Recall@K, MRR, and nDCG for vector,
lexical, and hybrid retrieval. The dataset and latest measured baseline are documented in
`evals/retrieval/README.md`. A cross-encoder reranker is intentionally not included yet: the current
small corpus does not justify its latency and operational cost. Approximate database vector search
can replace the exact in-process index when corpus scale requires it.

## Simulator API

Start the API after migrating and seeding the database:

```powershell
.\.venv\Scripts\uvicorn.exe resolveops.api.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for the generated API documentation. Customer Operations
simulators are under `/simulator/v1`; Employee/IT reads are under `/simulator/v1/it`. They provide
read access to the local enterprise-system simulator records.

All simulator routes require a configured bearer API key. The authenticated identity supplies the
tenant and role; clients cannot select either value. Multi-tenant deployments use a separate
database per tenant. Agents receive masked PII, while roles with the explicit `read_pii` permission
receive full values. Local configuration and rotation guidance are in `docs/SECURITY.md`.

The API rejects bodies larger than 1 MiB by default and applies a bounded token-bucket limit to
both the client network identity and a one-way digest of any presented bearer credential. Health
probes are exempt so deployment health checks cannot lock themselves out. Successful responses
include rate-limit metadata; rejected bursts receive HTTP 429 plus `Retry-After`. Limits are
configurable through the documented `RESOLVEOPS_*` environment settings.

The simulator routes are intentionally read-only. Write operations are available only through the
internal typed action tools; they are not public HTTP endpoints.

## Operator console

Start the migrated and seeded API, then open `http://127.0.0.1:8000/console`. The responsive
operator console presents the synthetic backend through four operational views:
an operational overview, Customer Operations evidence, Employee/IT access evidence, and reliability
signals. It reads the same authenticated, tenant-isolated simulator APIs and protected Prometheus
endpoint used by other clients; the screen is not filled with hard-coded success data.

Choose **Connect securely** and provide a configured Operator, Approver, or System API key. The key
is held only in the page's JavaScript memory. It is not written to local storage, session storage,
URLs, traces, or metrics, and it disappears when the page closes or the operator disconnects. Use
synthetic data only. The console is read-only: refunds, notifications, and access grants
remain behind the internal deterministic authorization and approval layer.

See `docs/OPERATOR_CONSOLE.md` for the demonstration flow, security boundary, and screenshot rules.

## Safe operations

The internal action layer supports issuing a refund, sending a customer email, creating a support
ticket, and granting approved repository access. Each operation applies deterministic controls
before changing data:

- role-based permission checks and USD refund limits
- confirmed issue, payment, return, currency, and amount rules
- a unique idempotency key that makes safe retries return the original result
- a durable audit trail for requested, authorized, denied, failed, executed, and verified states
- a fresh database read after execution before the operation is marked complete

An AI recommendation cannot bypass these controls or directly issue a refund. Amounts above an
actor's limit return an approval-required error. Agents cannot refund; operators can approve up to
500 USD, and approvers or the system can approve up to 5,000 USD. `Actor` values must come from a
trusted authentication boundary and must never be accepted directly from an untrusted request.

The current notification simulator supports only email sent to the customer's stored address; SMS
remains blocked until verified phone data exists. External provider connections are intentionally
left for later roadmap packets.

## Employee and IT access workflow

`EmployeeAccessWorkflow` handles the ML Platform onboarding scenario using the shared runtime. It
checks active employment, identity ownership, MFA, active team membership, the linked Git account,
repository ownership, exact manager approval, policy evidence, and existing access. It then uses the
shared idempotent and audited action layer to create the required directory-group membership and
repository grant, resolve the request, case, and ticket, notify the employee, and independently
verify the final state.

All directory, Git, ticket, and notification integrations are simulators. Model reasoning is
optional and advisory; it cannot bypass a deterministic check or perform an action. See
`docs/EMPLOYEE_IT.md` for the architecture, API, evaluation, and limitations.

## Case workflow orchestration

`CustomerIssueWorkflow` uses LangGraph to coordinate a typed, deterministic workflow for one issue
inside a case. It loads the case, routes by issue type, independently investigates current backend
state, retrieves applicable policy with citations, applies deterministic action gates, executes the
existing safe refund tool when authorized, and performs another fresh database read before reporting
an action as verified.

The terminal paths are intentionally different:

- `action_verified` means the requested refund record exists and matches the authorized request. It
  does not mean the external payment provider has completed the refund, so the case stays open.
- `waiting_external` means an active refund already exists and no duplicate action was taken.
- `needs_review` means evidence, persisted issue state, policy, authorization, or verification was
  insufficient. The workflow completes without silently bypassing the failed gate.

The workflow has one optional, bounded LLM reasoning role. It synthesizes collected evidence and
retrieved policy into a structured advisory assessment with evidence IDs, policy chunk citations,
missing information, risk notes, and a recommended disposition. A model recommendation cannot set a
refund amount, authorize an action, invoke a tool, change workflow state, or mark a case resolved.
Unknown citations, contradictory structured output, provider failures, and non-supportive
recommendations fail closed to review. The workflow still operates deterministically when no model
provider is configured.

The optional OpenAI adapter uses the
[Responses API structured-output parser](https://developers.openai.com/api/docs/guides/structured-outputs)
with the same Pydantic schema used by the application. Install the `llm` extra, construct
`OpenAIReasoningProvider` with an authenticated `OpenAI` client and an explicitly selected model, and pass it to
`CustomerIssueWorkflow`. No API key or model name is stored in the repository, and tests use an
offline scripted provider rather than making paid network calls.

`GeminiReasoningProvider` supplies the optional live-model reasoning path.
It uses the same advisory schema and system boundary, limits serialized input and output tokens,
sets a request timeout, and permits at most two provider attempts by default. A refusal, malformed
response, unknown citation, exhausted free quota, or provider failure fails closed instead of
authorizing an action. The API key is optional and must be supplied only through
`RESOLVEOPS_GEMINI_API_KEY`; it is never stored in the repository. The synthetic live gate was run
on 2026-09-28 with `gemini-3.5-flash-lite`: all 3 cases passed, the median observed latency was
4.74 seconds (range 1.49-6.77 seconds), and the provider reported 1,589 total tokens. These are
observations from that small run, not general model-quality or production-latency claims.

### Durable execution and human approval

Production workflow execution can use PostgreSQL-backed LangGraph checkpoints together with the
application's audited workflow lifecycle tables. Configure `CustomerIssueWorkflow` with both an
`open_postgres_checkpointer(...)` checkpointer and a `WorkflowLifecycleStore`, then call `start()`.
The checkpointer uses an explicit deserialization allowlist and synchronous durability. Its `setup()`
call creates LangGraph's internal checkpoint tables on first use; the normal Alembic migration owns
the ResolveOps workflow, approval, and event tables.

When a refund is above an operator's limit but within an approver's limit, `start()` returns a
`WorkflowPause` containing one persisted approval request. A trusted approver or system actor can
later send a typed `WorkflowApprovalDecision` to `resume()`. Approval continues from the stored
checkpoint and executes the existing deterministic action controls. Rejection ends in review with
no refund. Repeated starts, approval creation, and terminal lifecycle writes are idempotent, and
every lifecycle transition is stored as an ordered event.

The basic `run()` method remains available for non-durable local execution. It does not invent an
approval result and still fails closed when the caller lacks authority. A background worker is not
included because the current workflow has no long-running task that requires one.

### Reliability and recovery

Action execution uses a bounded `ReliabilityPolicy`. Only failures explicitly classified as
transient are retried. Retries use capped exponential backoff, the same idempotency key, durable
attempt counts, and an execution lease. Authorization failures, approval failures, invalid business
state, and changed idempotency payloads are never retried.

Database-backed simulator actions run inside a transaction-bound attempt deadline. If an attempt
returns after its deadline or raises before commit, the transaction rolls back before the next
attempt. A crashed `started` operation can be reclaimed only after its lease expires. If the action
was already committed, recovery is verify-only: ResolveOps performs fresh reads and never executes
the action again. Completed idempotent replays are also re-verified instead of trusting the old
success record.

Every attempt, scheduled retry, lease recovery, verification retry, and compensation decision is
stored as an ordered reliability event. `get_recovery_plan()` explains whether to wait, retry,
verify only, or require manual review. `recover_refund()`, `recover_notification()`, and
`recover_ticket()` provide explicit verify-only recovery for committed actions. ResolveOps does not
automatically reverse refunds or customer communications; those potentially harmful compensations
are marked for manual review. The full failure matrix and timeout boundary are documented in
`docs/RELIABILITY.md`.

## MCP and event interfaces

The optional `interfaces` dependency adds a local stdio MCP server with five read-only tools for
case, refund, policy, workflow, and recovery inspection. Write actions intentionally remain behind
the internal deterministic authorization layer. Run it with `resolveops-mcp` after configuring the
database.

The API also accepts authenticated payment-provider refund status events at
`POST /events/v1/refund-status`. HMAC verification, a replay window, durable event-ID idempotency,
per-tenant secrets, per-refund ordering, allowed state transitions, and stored rejection reasons
prevent duplicated, cross-tenant, or out-of-order delivery from silently corrupting refund state.
Configuration and the exact signing contract are documented in `docs/INTERFACES.md`.

## Security

ResolveOps uses authenticated tenant routing, database-per-tenant isolation, server-side RBAC, PII
masking, tenant-specific webhook secrets, secret-safe settings, and a pre-storage malicious-policy
guard. It also enforces request-size and rate limits before business processing. Retrieved knowledge
and evidence remain untrusted data, and model output remains advisory.
See `docs/SECURITY.md` for configuration and limitations and `docs/THREAT_MODEL.md` for threats,
controls, and residual risk.

## Evaluation and regression

ResolveOps keeps retrieval quality separate from workflow correctness. The retrieval benchmark
measures Recall@K, MRR, and nDCG on 50 policy questions. Deterministic workflow benchmarks run 24
Customer Operations cases and 14 Employee/IT access cases through the real workflows and check
outcomes, permissions, persistence, policy citations, failure handling, and verification.

Run the workflow regression gate with:

```powershell
.\.venv\Scripts\python.exe -m resolveops.evaluation.run
```

The current checked-in result is 24 of 24 cases passing. This is a reproducible regression result,
not a claim of general production accuracy. See `docs/EVALUATION.md` for the design, limitations,
and semantic-evaluation decision.

Run the Employee/IT regression gate with:

```powershell
.\.venv\Scripts\python.exe -m resolveops.evaluation.run_employee
```

Its current checked-in result is 14 of 14 cases passing.

## Observability and measured performance

ResolveOps emits structured parent/child traces for HTTP requests, workflows, graph nodes, policy
retrieval, action tools, retries, and bounded model calls. HTTP responses include a trace ID. Trace
attributes exclude request bodies, evidence, policy text, prompts, model outputs, customer PII,
credentials, and exception messages.

Authenticated Operator, Approver, and System identities can scrape Prometheus text metrics from
`GET /metrics`. The endpoint exports bounded-label HTTP totals, response-duration histograms,
in-progress requests, and pre-processing rejection totals. It never labels metrics with credentials,
tenant IDs, case IDs, request bodies, or raw URLs.

Run the reproducible offline workflow benchmark with `resolveops-observe`, or use:

```powershell
.\.venv\Scripts\python.exe -m resolveops.observability.benchmark `
  --warmup-runs 1 --runs 3 `
  --output evals/performance/customer_operations_local.json
```

The checked-in run contains 72 measured workflows and preserves real p50/p95 component timings.
It uses SQLite, local deterministic embeddings, and an offline scripted reasoner, so it is not a
production latency or scale claim. See `docs/OBSERVABILITY.md`, `docs/PERFORMANCE.md`, and
`docs/FAILURE_ANALYSIS.md`.

An optional three-case live Gemini gate checks real structured reasoning, citations, latency, and
provider-reported token usage over synthetic data. It is excluded from required CI because it uses
external quota. See `docs/EVALUATION.md` for the command, privacy limitation, and reporting rules.

## Deployment

ResolveOps includes a non-root multi-stage Docker image and a Compose stack with PostgreSQL,
one-shot migrations, migration-aware readiness, and an optional repeatable demo seed. The AWS
design uses Terraform for a two-AZ VPC, private ECS Fargate tasks, private encrypted RDS PostgreSQL,
an Application Load Balancer, ECR, Secrets Manager, CloudWatch logs/alarms, and restricted security
groups.

CI runs code quality, local tests, PostgreSQL integration, a real Compose deployment check, Terraform
validation, credential-pattern scanning, Bandit, and dependency vulnerability auditing. Third-party
GitHub Actions are pinned to reviewed commit SHAs, and Dependabot monitors Python, Actions, Docker,
and Terraform dependencies. The manual AWS workflow uses GitHub OIDC, immutable commit-SHA images,
and a migrate-before-service rollout. No AWS environment has been created from this repository yet. See
`docs/DEPLOYMENT.md` for local commands, cloud prerequisites, deployment order, verification,
rollback, cost-sensitive choices, and limitations.

The same container also packages the operator console at `/console`; it requires no separate frontend
service, third-party JavaScript, font CDN, or browser build step.

## Checks

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe scripts\security_check.py
.\.venv\Scripts\python.exe -m bandit -r src -q -ll
.\.venv\Scripts\python.exe -m pip_audit --local --skip-editable
docker compose config --quiet
terraform -chdir=infra/terraform fmt -check -recursive
terraform -chdir=infra/terraform validate
```

PostgreSQL integration tests require a dedicated database whose name contains `test`:

```powershell
$env:RESOLVEOPS_TEST_DATABASE_URL = "postgresql+psycopg://user:password@localhost/resolveops_test"
.\.venv\Scripts\python.exe -m pytest -m postgres
```
