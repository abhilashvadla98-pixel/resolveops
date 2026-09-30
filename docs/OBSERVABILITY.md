# ResolveOps observability

## Trace model

ResolveOps emits one structured event when a measured span finishes. A trace carries a random
128-bit trace ID plus the workflow ID and case ID when a workflow is active. Nested spans carry a
parent span ID, allowing a workflow to be reconstructed across:

- end-to-end workflow execution;
- each LangGraph node;
- hybrid policy retrieval;
- controlled action tools;
- retry scheduling;
- bounded LLM reasoning; and
- HTTP requests.

The default sink writes a single JSON object prefixed by `resolveops_trace` to the
`resolveops.observability` logger. Tests and measurements inject an in-memory sink. When
`RESOLVEOPS_OTLP_ENDPOINT` is configured and the `observability` extra is installed, the same safe
completed events are also mapped to OpenTelemetry spans and exported over OTLP/HTTP. Exporter
startup and delivery failures fall back to local structured traces and never block business work.

HTTP responses include `X-ResolveOps-Trace-ID`. API spans store the HTTP method, route template, and
status code. They do not store query strings or request/response bodies. Workflow spans store IDs,
component names, operation names, durations, status, terminal workflow outcome, and small bounded
attributes. Evidence, policy text, customer data, prompts, model output, credentials, and exception
messages are deliberately excluded.

## Metrics

`summarize_trace_events()` groups measured spans by component and operation. It reports call and
failure counts, minimum, p50, p95, and maximum observed latency using the nearest-rank percentile
method. It also reports workflow outcome counts, scheduled retries, and trace/event counts.

The running API exposes Prometheus-compatible text at `GET /metrics`. The endpoint requires bearer
authentication and allows only Operator, Approver, or System roles. It exports:

- `resolveops_http_requests_total` by method, route template, and status code;
- `resolveops_http_request_duration_seconds` by method and route template;
- `resolveops_http_requests_in_progress` by method; and
- `resolveops_http_rejections_total` by bounded rejection reason;
- `resolveops_agent_runs_total` and role latency by bounded role/status labels;
- `resolveops_agent_tokens_total` by role and input/output direction;
- `resolveops_agent_tool_calls_total` by allowlisted tool and terminal status; and
- `resolveops_agent_queue_jobs` by pending/running/retrying/dead-letter status.

Labels deliberately exclude tenant, user, case, workflow, credential, query-string, and raw-path
values to prevent secrets and unbounded cardinality. Prometheus can send a configured operations
API key as its bearer token when scraping.

An exception makes its span an error and records only the exception class. A workflow can still be
successful from an engineering perspective when a child tool or model span fails: deterministic
workflow handling may correctly route the case to review. The evaluation report remains the source
of final-state correctness; a raw tool error rate is not a task-success metric.

The model adapters capture input, output, and total token counts when providers return usage.
Cost remains null unless both input and output prices are explicitly configured. With configured
prices, the shared ledger computes workflow cost from recorded tokens and can stop before exceeding
`RESOLVEOPS_AGENT_COST_LIMIT_USD`; ResolveOps never guesses price from a model name.

## Reproducing the local measurement

Run:

```powershell
.\.venv\Scripts\python.exe -m resolveops.observability.benchmark `
  --warmup-runs 1 --runs 3 `
  --output evals/performance/customer_operations_local.json
```

The command runs the checked-in 24-case workflow evaluation once as warm-up and three times as the
measured sample. It exits unsuccessfully if any evaluation case fails. Database creation, seeding,
and policy ingestion are excluded from workflow span latency; those setup costs belong to fixture
construction rather than an already-running workflow.

## Current limits

- OTLP is optional; this repository does not operate or claim a durable collector.
- Prometheus counters are process-local. The checked-in container runs one API worker; a future
  multi-worker or horizontally scaled deployment must use the Prometheus multiprocess mode or a
  compatible metrics collector before aggregating these values.
- No production concurrency, throughput, saturation, queue time, network latency, or uptime has
  been measured.
- The local benchmark uses in-memory SQLite, feature-hash embeddings, and an offline reasoning
  provider. It is a regression baseline, not a production capacity claim.
- No SLO or alert threshold is declared from this small local sample.
- Trace sampling, retention, external-collector redaction policy, and native cross-service parent
  propagation remain deployment responsibilities. ResolveOps correlation IDs are exported as span
  attributes, not reconstructed as remote OpenTelemetry parent contexts.
