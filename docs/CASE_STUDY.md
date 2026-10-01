# ResolveOps case study

## Problem

Customer support and employee-access work often begins with incomplete natural language, crosses
several systems, and can end in a high-impact action. A fluent answer is not enough: an operator
needs the evidence, controlling policy, approval state, execution record, and a fresh read proving
what actually changed.

ResolveOps is a production-minded operations system built around one boundary:

> AI may advise. Deterministic software authorizes, executes, audits, and verifies.

The project implements two connected domains: customer refund investigations and employee Git
access. All records and business-system integrations are synthetic or simulated. It does not claim
a live payment, identity, Git, or CRM connection.

## Constraints

- The application must work locally without a paid model or cloud account.
- Tenant and actor identity must come from authenticated server context, never the request body.
- Model output cannot authorize an action.
- Money and access changes require deterministic gates, idempotency, and fresh verification.
- Human approvals must be durable and auditable.
- Evaluation evidence must remain reproducible and must not hide failures or unlabeled data.
- A public demo must show real persisted queues and histories, not a static dashboard.

## System built

The FastAPI service exposes a compact operations console, authenticated APIs, PostgreSQL-backed
records, durable LangGraph workflows, versioned policy retrieval, optional structured model advice,
human approval, controlled actions, final-state verification, Prometheus metrics, and ordered audit
events. SQLite supports the no-cost local demo; PostgreSQL is used for concurrency and scale proof.

The optional deep-analysis path uses a LangGraph supervisor over Customer Operations and Employee/IT
subgraphs. Five separately invoked roles plan, select allowlisted reads, retrieve policy, propose an
issue-separated resolution, and independently criticize it. They exchange typed state and persist
run/tool telemetry. They cannot approve or execute. PostgreSQL owns queued work; Redis/Valkey only
wakes workers and coordinates shared rate limits.

The operator console has five working areas:

1. **Cases** — searchable, paginated customer queue and three-pane investigation workspace.
2. **Approvals** — durable pending decisions with operator notes.
3. **IT Requests** — multiple persisted employee-access cases and their evidence.
4. **Reliability** — measured lifecycle summaries and operation traces.
5. **Audit** — global workflow and action history with case filtering.

Operators can correct an AI assessment with structured feedback. Feedback begins as pending, is
reviewed separately, and is never promoted into evaluation truth automatically.

## Closed owner-feedback loop

On September 30, 2026, the live multi-agent and walkthrough checks exposed a real operator-facing
failure: after agent validation failed, the case panel continued to show the generic
`Workflow outcome · Not started` state. The owner explicitly approved this correction:

> Do not present a refund as ready for approval when evidence or policy citations are incomplete;
> disclose the validation failure and block approval.

The reviewed correction was promoted as `FDBK-EX-owner-ui-001` in owner-corrections dataset
version 1.0.0. The console now renders `Investigation stopped safely`, marks approval blocked,
states that no sensitive action ran, and identifies complete evidence and policy citations as the
required next step. The focused Playwright regression
`test_failed_agent_validation_blocks_approval_and_explains_safe_stop` reproduces a failed agent
request and verifies those controls. This is one real closed loop, not an automated or invented
labeling claim.

## Data and evaluation design

A deterministic generator creates connected customer, order, payment, return, refund, case,
workflow, approval, action, verification, audit, reliability, employee, identity, team, Git,
ticket, and notification records. It supports configurable seeds, anomaly rates, and four size
profiles. Each output includes exact row counts, anomaly labels, SHA-256 checksums, and a versioned
manifest.

Loading is fail-closed. Twelve checks cover manifest integrity, unique identifiers, foreign keys,
tenant isolation, currency consistency, refund limits, return chronology, approval order, fresh
verification, active policy, timestamp order, and supported states. The validator reports exact
failures and never silently repairs data.

Seven evaluation datasets are independently versioned and hashed:

| Dataset | Examples | Purpose |
| --- | ---: | --- |
| Retrieval | 50 | policy search, hard negatives, similar policies, multi-section answers |
| Customer workflow | 24 | end-to-end outcome, persistence, policy, and node assertions |
| Employee/IT workflow | 14 | identity, MFA, approval, access, conflict, and replay paths |
| Response candidates | 24 | deterministic safety checks plus separate human review |
| Live reasoning | 3 | optional external-model structured reasoning boundary |
| Agent trajectories | 22 | five-role routing, tools, replanning, escalation, and budgets |
| Adversarial security | 17 | known prompt/tool/secret attacks plus benign controls |

Experiment artifacts record the Git revision, dataset ID/version/hash, model/provider, prompt and
schema versions, embedding/retrieval configuration, policy index version, metrics, latency,
provider-reported tokens/cost, and failure counts. Human response review exports a six-question
rubric and imports proposed labels into a separate candidate artifact; current truth remains
explicitly **0/24 human-reviewed**.

## Three failures that changed the system

### 1. Generated authorization-hold cases violated financial state

A 100-case data-quality run found two refund paths attached to an uncaptured authorization-hold
payment. The generator was corrected so authorization holds cannot enter the resolved refund path.
The same twelve checks then passed with zero failures. This is a real example of the validator
finding a generator bug before database load.

### 2. The case queue degraded with data size

At 10,000 customer cases, PostgreSQL used a sequential scan and top-N sort. The inspected plan took
11.903 ms, and the repeated query measured 5.899 ms p50 / 7.455 ms p95. An evidence-driven index on
`cases.updated_at` changed the plan to a backward index scan at 0.035 ms. The repeated measurement
improved to 3.510 ms p50 / 4.090 ms p95. The database grew by about 1.03 MB at that scale, which is
the explicit storage/write-maintenance tradeoff.

### 3. An unpaced load test hit protection, not capacity

An intentionally unpaced six-worker run sent 15,355 requests in 30 seconds. It produced 15,177
errors because the application rate limiter correctly rejected traffic above its configured
boundary. That run is preserved as saturation evidence, not presented as normal performance. A
paced follow-up sent 90 read-only requests over 60.58 seconds at 1.486 requests/second: all 90
returned HTTP 200, with 16 ms p50 and 47 ms p95 client-observed latency.

### 4. Reranking improved quality but failed the latency rule

The measured cross-encoder reranker moved MRR from 0.9233 to 0.9367 and nDCG from 0.9363 to 0.9531,
but increased local p95 from about 45.75 ms to 1,179.72 ms. Because the adoption rule required p95
at or below 250 ms, the system retained the simpler hybrid retriever. The rejected feature and its
artifact remain in the repository rather than being presented as a production improvement.

## Measured evidence

The isolated PostgreSQL benchmark completed at 1,523, 15,178, and 151,862 generated records. The
largest point contained 10,000 customer cases and 2,500 IT requests, loaded in 34.460 seconds, and
used 49,390,095 database bytes after the queue index. At that point, direct-query p95 was 4.090 ms
for the case list and 15.093 ms for hybrid retrieval in the pre-index run; retrieval was unaffected
by the queue index.

The established offline workflow suite currently reports 24/24 customer and 14/14 employee/IT
cases passing. The retrieval set reports Recall@3 of 0.920 for FastEmbed, 0.980 for BM25, and 0.980
for hybrid. BM25 beat hybrid on MRR and nDCG in this small corpus; the less flattering result is
kept visible. These are repository regression and local benchmark results, not production accuracy,
SLO, or business-impact claims.

The five-role trajectory suite reports 22/22 contract cases passing, including replanning,
escalation, forbidden writes, tenant/memory safety, and both domains. A mixed API run completed
232/232 requests with 30 case writes, while eight PostgreSQL workers claimed 200/200 durable jobs
once with no duplicate claim. Both are bounded desktop evidence, not production capacity.

## Reliability, security, and recovery

Actions use typed requests, server-derived actors, database transactions, unique idempotency keys,
bounded retries, ordered events, and fresh verification. A committed-but-unverified action enters
verify-only recovery instead of being blindly repeated. PostgreSQL tests cover competing refunds,
duplicate approval decisions, and repeated webhooks. A guarded backup/restore drill refuses unsafe
database names.

Secrets, prompts, policy text, model outputs, request bodies, and customer PII are excluded from
trace attributes. Demo tokens stay in memory. Production startup rejects SQLite, placeholder
secrets, unsafe demo settings, and missing identities.

## Deployment position

The repository contains a locked non-root container, migration-gated Compose stack, CI, a live
synthetic Render demo, and an AWS ECS API/worker, RDS, TLS Valkey, ALB, ECR, Secrets Manager, and
CloudWatch Terraform design. The Render deployment is recorded separately from local measurements.
The AWS design has not been provisioned and would require the owner's account, cost choice,
credentials/OIDC, secrets, and explicit authorization.

## What 10× and 100× would require

The completed 10,000-case measurement is a useful local proof, not a forecast. A 10× production
path would require representative traffic mixes, PostgreSQL server metrics, connection-pool tuning,
shared rate limiting, deeper mutation and approval tests, and SLOs based on real demand. A 100× path
would additionally require partitioning/retention decisions for audit history, worker autoscaling,
managed observability, disaster-recovery
targets, realistic external-provider fault testing, and security/operational review.

The most important remaining product gaps are real system connectors, enterprise SSO, calibrated
human labels, a larger representative evaluation set, and production load evidence. They are
stated directly rather than hidden behind architecture diagrams.
