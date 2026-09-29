# ResolveOps

ResolveOps is a production-minded AI operations system for investigating customer and employee
cases, grounding recommendations in versioned policy, pausing risky actions for human approval, and
proving the final state after execution.

It is built to demonstrate a boundary that matters in real AI engineering:

> The model may advise. Deterministic software authorizes, executes, audits, and verifies.

The repository includes a working operator console, two end-to-end business domains, durable
workflows, PostgreSQL persistence and concurrency controls, retrieval and workflow evaluations,
reliability evidence, browser automation, deployment infrastructure, and recovery drills. All
checked-in business data is synthetic. No live payment, CRM, identity, Git, ticketing, or cloud
account is connected.

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
6. Open **IT Requests**, run the controlled access workflow, and show the verified final records.
7. Run it again to show that ResolveOps detects existing access and creates no duplicate grant.

The same journey is exercised in Chromium by `tests/test_browser_e2e.py`.

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
| Response safety/grounding candidates | 24/24 automated checks passed; **0/24 human-reviewed** |
| Retrieval set | 50 hand-authored queries |
| FastEmbed vector Recall@3 / MRR / nDCG@3 | 0.9200 / 0.9100 / 0.9024 |
| BM25 Recall@3 / MRR / nDCG@3 | 0.9800 / 0.9467 / 0.9418 |
| Hybrid Recall@3 / MRR / nDCG@3 | 0.9800 / 0.9233 / 0.9363 |
| Offline workflow timing sample | 72 workflows; p50 19.29 ms, p95 34.92 ms |
| Optional Gemini synthetic gate | 3/3 passed on the recorded 2026-09-28 run |

BM25 beat hybrid on MRR and nDCG in the measured small corpus. That result is kept visible instead of
selecting only the most flattering metric. The 24 response candidates have deterministic safety and
grounding checks, but remain explicitly pending human tone/usefulness review.

Reproduce the main gates:

```powershell
uv run --locked python -m resolveops.evaluation.run
uv run --locked python -m resolveops.evaluation.run_employee
uv run --locked python scripts/run_response_evaluation.py
uv run --locked python -m resolveops.knowledge.evaluate --provider fastembed --k 3
uv run --locked python -m pytest
```

Detailed methodology and limitations live in [Evaluation](docs/EVALUATION.md),
[retrieval results](evals/retrieval/README.md), and
[response review](evals/responses/README.md).

## Observability

The console and authenticated APIs expose:

- p50/p95 operation lifecycle duration calculated from persisted records;
- operation outcomes, failures, retries, waits, recovery, and manual-review counts;
- clickable reliability-event traces for recent operations;
- ordered workflow lifecycle events;
- bounded-label Prometheus HTTP counters and histograms at `/metrics`;
- a request trace ID for correlation with structured server logs.

Trace attributes exclude credentials, request bodies, prompts, model outputs, policy text, evidence,
and customer PII. OpenTelemetry export was not added: the current single-service demo has structured
traces and Prometheus metrics, and adding an exporter without a real backend would create setup with
no new evidence.

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

See [Security](docs/SECURITY.md) and the six decisions in [ADRs](docs/adr/).

## Deployment status

The repository contains a locked, non-root multi-stage image, a migration-gated Compose stack, and
Terraform for private ECS Fargate, RDS PostgreSQL, ALB, ECR, Secrets Manager, and CloudWatch. CI
checks quality, security, PostgreSQL, the container, browser behavior, and Terraform.

No public cloud environment is currently deployed, and the repository does not claim otherwise.
The AWS design can incur charges. A public deployment requires the owner's cloud account, cost
choice, credentials/OIDC setup, secrets, and explicit launch authorization. The local demo provides
the complete recruiter walkthrough without paid infrastructure. See
[Deployment](docs/DEPLOYMENT.md) for the exact order, rollback, and cost/resilience tradeoffs.

## Repository map

```text
src/resolveops/          API, workflows, actions, security, retrieval, observability
domain_packs/            versioned policies and domain fixtures
migrations/              Alembic schema history
evals/                   retrieval, workflow, response, reasoning, and timing evidence
tests/                   unit, security, PostgreSQL, migration, and browser tests
infra/terraform/         reviewed AWS reference deployment
docs/adr/                architecture decision records
```

Recommended reading:

- [Operator console](docs/OPERATOR_CONSOLE.md)
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
- Rate limiting is process-local and must move to a gateway or shared store before horizontal scale.
- There is no enterprise SSO, customer-facing portal, background worker, or public cloud instance.
- The retrieval corpus is deliberately small, and the measured scores must not be generalized.
- Human review of the 24 customer-response candidates is still pending.
