# ResolveOps

ResolveOps is a production-minded AI operations system for investigating customer and employee
cases, grounding recommendations in versioned policy, pausing risky actions for human approval, and
proving the final state after execution.

It also includes an explicit, manually started hierarchical multi-agent analysis path with a
Supervisor, tool-using Investigator, Policy specialist, Resolution specialist and independent
Critic. The five roles remain advisory; the proven deterministic control plane still authorizes,
executes and verifies every sensitive action. See
[Hierarchical multi-agent analysis](docs/MULTI_AGENT_ARCHITECTURE.md).

It is built to demonstrate a boundary that matters in real AI engineering:

> The model may advise. Deterministic software authorizes, executes, audits, and verifies.

The repository includes a working operator console, two end-to-end business domains, durable
workflows, PostgreSQL persistence and concurrency controls, retrieval and workflow evaluations,
reliability evidence, browser automation, deployment infrastructure, and recovery drills. All
checked-in business data is synthetic. No live payment, CRM, identity, Git, ticketing, or cloud
account is connected.

**Portfolio links:** [watch the 42-second product demo](https://github.com/abhilashvadla98-pixel/resolveops/releases/download/recruiter-demo-v1/resolveops-recruiter-demo.webm) ·
[run the local demo](#try-the-complete-demo-locally) ·
[recording script](docs/DEMO_SCRIPT.md) ·
[multi-agent architecture](docs/MULTI_AGENT_ARCHITECTURE.md) ·
[measured evidence](#evaluation-evidence) ·
[engineering case study](docs/CASE_STUDY.md)

There is no hosted “Live Demo” link because no public cloud environment has been deployed. The
complete synthetic demo runs locally without a model key or paid service.

Long multi-agent analysis also has an optional background path: PostgreSQL owns durable jobs and
events, a leased worker executes them, Redis carries wake-up markers and shared rate-limit state,
and the console receives safe role progress over authenticated SSE. The normal local demo still
works without Redis.

## What the product does

### Customer Operations

- accepts a natural-language complaint and persists separate issues;
- reads current customer, order, payment, return, and refund state;
- retrieves active policy with version and section citations;
- optionally asks a bounded model for structured advice;
- applies deterministic permission, amount, business-state, idempotency, and approval gates;
- creates a simulated refund only when authorized;
- reads the state again before reporting that the refund record was created;
- never claims that an external payment provider completed settlement.

### Employee and IT Operations

- verifies active employment, enterprise identity ownership, MFA, team membership, Git identity,
  repository ownership, and exact manager approval;
- retrieves the active access policy;
- grants the minimum approved repository access through an idempotent action;
- verifies directory group membership, repository access, request, case, ticket, and notification
  state from fresh reads;
- returns no action on an exact replay and escalates partial or conflicting access.

## Architecture

```mermaid
flowchart LR
    UI[Operator console] --> API[FastAPI boundary]
    CLIENT[API / MCP client] --> API
    API --> AUTH[Authentication, tenant routing, RBAC]
    AUTH --> WF[LangGraph workflows]
    WF --> READS[Typed simulator reads]
    WF --> RETRIEVAL[Versioned policy retrieval]
    RETRIEVAL --> ADVICE[Optional structured model advice]
    ADVICE --> GATES[Deterministic safety gates]
    READS --> GATES
    GATES --> APPROVAL[Durable human approval]
    APPROVAL --> ACTIONS[Idempotent action tools]
    ACTIONS --> VERIFY[Fresh-state verification]
    VERIFY --> DB[(PostgreSQL / local SQLite)]
    API --> OBS[Metrics and structured traces]
    ACTIONS --> AUDIT[Audit and reliability events]
    AUDIT --> DB
```

The optional agent path is a real five-role hierarchy rather than five names around one call:

```mermaid
sequenceDiagram
    participant O as Operator
    participant S as Supervisor
    participant I as Investigator
    participant P as Policy agent
    participant R as Resolution agent
    participant C as Independent critic
    participant D as Deterministic control plane
    O->>S: Start bounded analysis
    S->>I: Typed goal and evidence needs
    S->>P: Typed policy task
    par Independent reads
        I->>I: Choose allowlisted read tools
        P->>P: Search and refine retrieval
    end
    I-->>S: Facts, provenance, gaps
    P-->>S: Citations, versions, conflicts
    S->>R: Scoped evidence and policy
    R-->>C: Issue-separated proposal
    C-->>S: Accept, revise, or escalate
    S-->>D: Advisory result only
    D->>D: Authorize, approve, execute, verify
```

```mermaid
flowchart TD
    A[Complaint or access case] --> B[Load independent evidence]
    B --> C[Retrieve active policy]
    C --> D[Optional advisory assessment]
    D --> E{Deterministic gates pass?}
    E -- No --> F[Escalate with reason]
    E -- Approval required --> G[Persist pause and wait]
    G --> H{Human decision}
    H -- Reject --> F
    H -- Approve --> I[Execute once with idempotency key]
    E -- Yes --> I
    I --> J[Read final state again]
    J -- Verified --> K[Grounded response and audit trail]
    J -- Uncertain --> L[Verify-only recovery or review]
```

## Try the complete demo locally

Requirements: Python 3.12. Docker is optional for this quick SQLite demo.

```powershell
python -m pip install "uv==0.12.20"
uv sync --locked --all-extras

$env:RESOLVEOPS_ENVIRONMENT = "development"
$env:RESOLVEOPS_DATABASE_URL = "sqlite:///./resolveops-demo.db"
$env:RESOLVEOPS_DEFAULT_TENANT_ID = "TENANT-DEMO"
$env:RESOLVEOPS_TENANT_DATABASE_URLS_JSON = '{"TENANT-DEMO":"sqlite:///./resolveops-demo.db"}'
$env:RESOLVEOPS_WEBHOOK_SECRET = "local-demo-webhook-secret-at-least-32-chars"
$env:RESOLVEOPS_DEMO_ENABLED = "true"
$env:RESOLVEOPS_DEMO_TENANT_ID = "TENANT-DEMO"
$env:RESOLVEOPS_DEMO_SESSION_SECRET = "local-demo-session-secret-at-least-32-chars"

uv run --locked alembic upgrade head
uv run --locked python -m resolveops.database.seed
uv run --locked uvicorn resolveops.api.main:app
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). ResolveOps opens the operator console
automatically; choose **Try demo**.
No model key or paid service is required. The seed command builds a deterministic local policy index.

For the persistent local Docker version, copy `compose.env.example` to an ignored `.env.compose`,
replace its two local secrets, then run `docker compose --env-file .env.compose --profile demo up
--build`. The development Compose stack enables only the restricted synthetic demo workspace by
default; production startup continues to reject demo mode.

![ResolveOps Customer Operations workflow](docs/assets/resolveops-customer-workflow.png)

| Reliability evidence | Verified Employee/IT access |
| --- | --- |
| ![ResolveOps reliability view](docs/assets/resolveops-reliability.png) | ![ResolveOps Employee and IT workflow](docs/assets/resolveops-employee-it.png) |

### Five-minute walkthrough

1. Submit a complaint and show that intake creates persisted issues but authorizes no action.
2. Select demo scenario D and start the refund investigation.
3. Open **Approvals**, add a decision note, and approve the paused action.
4. Return to the case and show the stored customer/order/payment/policy/advice/gate/execution/
   verification timeline and grounded final response.
5. Open **Reliability** and inspect measured lifecycle latency plus the operation event trace.
6. Open **IT Requests**, approve ITCASE-2002 with a written reason, run the controlled grant, and
   show the verified directory, repository, ticket, and notification records.
7. Run ITCASE-2004 to show that missing MFA produces a durable safety stop with no access, then
   inspect both the approval and terminal workflow in **Audit**.

The same journey is exercised in Chromium by `tests/test_browser_e2e.py`.

The console is deliberately an internal operations product rather than a marketing page. It uses
compact queues, filters and pagination, a three-pane case workspace, evidence and policy context,
durable approvals, operator corrections, real IT records, reliability traces, and a global audit
table. The default theme is neutral and light, with an optional dark mode.

The Approvals queue covers controlled refunds and employee repository-access requests. Pending IT
work cannot be processed until an explicit approve/reject decision with a written reason has been
persisted. Customer and IT workflow outcomes survive refresh, and **Reset demo** clears and rebuilds
both domains rather than leaving prior approval or access state behind. API tests separately prove
that replaying a completed access request creates no duplicate grant.

## Safety and recovery design

Every action uses a typed request, server-derived actor, unique idempotency key, database transaction,
ordered audit events, bounded retry policy, and fresh verification. A committed-but-unverified action
is never blindly repeated: recovery is verify-only. Refunds and customer communications do not have
automatic destructive compensation because a local inverse write cannot prove that an external side
effect was reversed.

Durable customer workflows use PostgreSQL-backed LangGraph checkpoints and application-owned run,
approval, and event tables. Real PostgreSQL tests cover simultaneous refund attempts, duplicate
approval decisions, and duplicate webhook delivery. `scripts/backup_restore_drill.py` performs a
guarded seed → backup → mutation → database recreation → restore → verification drill and refuses a
database name that does not contain `test` or `drill`.

See [Reliability](docs/RELIABILITY.md), [Failure cases](docs/FAILURE_CASES.md), and
[Threat model](docs/THREAT_MODEL.md).

## Evaluation evidence

These are reproducible repository results, not production accuracy or scale claims.

| Evidence | Current checked-in result |
| --- | --- |
| Customer workflow regression | 24/24 passed |
| Employee/IT workflow regression | 14/14 passed |
| Multi-agent trajectory regression | 22/22 passed across five roles, replanning, escalation, tools, and safety |
| Response safety/grounding candidates | 24/24 automated checks passed; **0/24 human-reviewed** |
| Adversarial input gate | 17/17 attack and benign-control cases passed |
| Retrieval set | 50 hand-authored queries |
| FastEmbed vector Recall@3 / MRR / nDCG@3 | 0.9200 / 0.9100 / 0.9024 |
| BM25 Recall@3 / MRR / nDCG@3 | 0.9800 / 0.9467 / 0.9418 |
| Hybrid Recall@3 / MRR / nDCG@3 | 0.9800 / 0.9233 / 0.9363 |
| Offline workflow timing sample | 72 workflows; p50 19.29 ms, p95 34.92 ms |
| Optional Gemini synthetic gate | 3/3 passed on the recorded 2026-09-28 run |
| Mixed API soak | 232/232 requests; 30 writes; p50 16 ms, p95 47 ms |
| PostgreSQL queue race | 200/200 jobs claimed once by 8 workers; 0 duplicates |

BM25 beat hybrid on MRR and nDCG in the measured small corpus. That result is kept visible instead of
selecting only the most flattering metric. The 24 response candidates have deterministic safety and
grounding checks, but remain explicitly pending human tone/usefulness review.

Reproduce the main gates:

```powershell
uv run --locked python -m resolveops.evaluation.run
uv run --locked python -m resolveops.evaluation.run_employee
uv run --locked python scripts/run_response_evaluation.py
uv run --locked python scripts/run_agent_evaluation.py
uv run --locked python scripts/run_security_evaluation.py
uv run --locked python -m resolveops.knowledge.evaluate --provider fastembed --k 3
uv run --locked python -m pytest
```

Detailed methodology and limitations live in [Evaluation](docs/EVALUATION.md),
[retrieval results](evals/retrieval/README.md), and
[response review](evals/responses/README.md).

## Synthetic data and the feedback flywheel

`scripts/generate_data.py` creates deterministic, connected operational histories for both product
domains. Demo, small, medium, and large profiles are configurable by exact customer-case count, IT
request count, seed, and anomaly rate. Each generated dataset includes a versioned manifest with
row counts, labels, and file hashes. `scripts/validate_data.py` runs twelve fail-closed integrity and
business checks before `scripts/load_data.py` will write anything.

The small checked-in fixture contains 307 records and passes all twelve checks. Larger generated
data stays out of Git. The completed PostgreSQL benchmark reached 151,862 records: 10,000 customer
cases and 2,500 IT requests.

The console can save structured operator corrections with case/workflow/trace context, original and
corrected values, reason, operator, and model/prompt metadata. Corrections remain pending until a
separate human review. They are never silently converted into evaluation ground truth.

Seven versioned manifests currently cover 154 examples. Lightweight
experiment artifacts bind results to a Git revision, exact dataset hash, model/prompt/schema,
retrieval/index configuration, latency, provider-reported usage/cost, and failure counts.

```powershell
uv run --locked python scripts/generate_data.py --profile demo --output generated-data/demo
uv run --locked python scripts/validate_data.py generated-data/demo
uv run --locked python scripts/load_data.py generated-data/demo
uv run --locked python scripts/export_response_review.py
```

See [Synthetic data](data/README.md), [experiment artifacts](experiments/README.md), and the
[complete engineering case study](docs/CASE_STUDY.md).

## Observability

The console and authenticated APIs expose:

- p50/p95 operation lifecycle duration calculated from persisted records;
- operation outcomes, failures, retries, waits, recovery, and manual-review counts;
- clickable reliability-event traces for recent operations;
- ordered workflow lifecycle events;
- bounded-label Prometheus HTTP counters and histograms at `/metrics`;
- a request trace ID for correlation with structured server logs.

Trace attributes exclude credentials, request bodies, prompts, model outputs, policy text, evidence,
and customer PII. An optional OTLP/HTTP exporter maps completed internal trace events to standard
OpenTelemetry spans while always retaining the local structured-log sink. Export failure cannot
break a workflow. No collector backend is bundled or claimed as deployed.

## Security boundaries

- The authenticated server identity chooses tenant and role; request bodies cannot.
- Each tenant maps to a separate database.
- Agents receive masked PII; explicitly permitted roles can read full values.
- Demo sessions are short-lived, signed, and restricted to the synthetic demo tenant.
- Webhooks use per-tenant HMAC secrets, timestamps, replay protection, event idempotency, and ordered
  state transitions.
- Non-development startup rejects SQLite/local/example databases, placeholder secrets, `TENANT-LOCAL`,
  unsafe demo settings, and missing production identities.
- The console keeps its token only in JavaScript memory and loads no CDN script, analytics, or remote
  font.

See [Security](docs/SECURITY.md) and the nine focused decisions in [ADRs](docs/adr/).

## Deployment status

The repository contains a locked, non-root multi-stage image, a migration-gated Compose stack, and
Terraform for private ECS Fargate API/worker services, RDS PostgreSQL, TLS Valkey, ALB, ECR,
Secrets Manager, and CloudWatch. CI
checks quality, security, PostgreSQL, the container, browser behavior, and Terraform.

No public cloud environment is currently deployed, and the repository does not claim otherwise.
The AWS design can incur charges. A public deployment requires the owner's cloud account, cost
choice, credentials/OIDC setup, secrets, and explicit launch authorization. The local demo provides
the complete recruiter walkthrough without paid infrastructure. See
[Deployment](docs/DEPLOYMENT.md) for the exact order, rollback, and cost/resilience tradeoffs.

## Measured scale and performance

The isolated PostgreSQL scale run completed at 1,523, 15,178, and 151,862 records. At the largest
point, the case queue exposed a sequential scan. A measured `updated_at` index changed the inspected
plan from 11.903 ms to 0.035 ms and repeated queue p95 from 7.455 ms to 4.090 ms, with an explicit
storage/write-maintenance tradeoff.

A paced read-only API soak completed 90/90 requests successfully over 60.58 seconds at 1.486
requests/second, with 16 ms p50 and 47 ms p95 client-observed latency. The earlier unpaced stress
run hit the designed rate limit; it is preserved as protection/saturation evidence and not presented
as backend capacity. See [Performance](docs/PERFORMANCE.md) and
[the index decision](benchmarks/scale/CASE_QUEUE_INDEX.md).

The isolated mixed follow-up completed 232/232 requests, including 30 case-intake writes, at 7.638
requests/second with 16 ms p50 / 47 ms p95. A separate PostgreSQL queue race claimed 200/200 jobs
exactly once across eight workers. These bounded desktop measurements are not production SLOs.

## Repository map

```text
src/resolveops/          API, workflows, actions, security, retrieval, observability
domain_packs/            versioned policies and domain fixtures
migrations/              Alembic schema history
evals/                   retrieval, workflow, response, reasoning, and timing evidence
data/                    synthetic data contracts, checked-in demo fixture, and manifests
experiments/             reproducible experiment artifact format and measured run metadata
benchmarks/              guarded scale/load runners and preserved measured results
tests/                   unit, security, PostgreSQL, migration, and browser tests
infra/terraform/         reviewed AWS reference deployment
docs/adr/                architecture decision records
```

Recommended reading:

- [Operator console](docs/OPERATOR_CONSOLE.md)
- [Engineering case study](docs/CASE_STUDY.md)
- [Engineering notes](docs/ENGINEERING_NOTES.md)
- [Code audit](docs/CODE_AUDIT.md)
- [Non-goals](docs/NON_GOALS.md)
- [Backup and restore](docs/BACKUP_RESTORE.md)
- [Interfaces](docs/INTERFACES.md)

## Quality gates

```powershell
uv lock --check
uv run --locked python -m pytest
uv run --locked ruff check .
uv run --locked mypy src
uv run --locked python scripts/security_check.py
uv run --locked bandit -r src -q -ll
uv run --locked pip-audit --local --skip-editable
docker compose config --quiet
terraform -chdir=infra/terraform fmt -check -recursive
terraform -chdir=infra/terraform validate
```

PostgreSQL-marked tests require a dedicated database whose name contains `test`:

```powershell
$env:RESOLVEOPS_TEST_DATABASE_URL = "postgresql+psycopg://user:password@localhost/resolveops_test"
uv run --locked python -m pytest -m postgres
```

## Current limitations

- Enterprise systems are simulators, not live vendor integrations.
- SQLite demo checkpoints are process-local; durable restart uses PostgreSQL.
- Rate limiting uses Redis when configured and a bounded process-local fallback during an outage;
  that fallback is not a substitute for distributed quota enforcement at sustained scale.
- There is no enterprise SSO, customer-facing portal, or public cloud instance. The worker/Valkey
  cloud architecture is validated Terraform, not a running deployment.
- The retrieval corpus is deliberately small, and the measured scores must not be generalized.
- Human review of the 24 customer-response candidates is still pending.
- The five-role offline trajectory gate validates orchestration contracts, not broad live-model
  quality. Dollar cost remains unknown until explicit provider pricing is configured and measured.
