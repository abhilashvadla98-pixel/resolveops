# ResolveOps cost analysis

ResolveOps can run its complete deterministic demo, automated evaluations, and offline multi-agent
contract suite without a paid model or cloud account. Dollar cost is reported only when an operator
configures both model prices and receives token usage. Unknown cost remains unknown.

## Measured model usage

The 22-case offline trajectory report made 182 deterministic provider-double invocations: 8.27 per
case. It estimated 71,991 input-context tokens, or 3,272 per case, and made no external provider
requests. Output tokens and dollar cost are therefore zero/unknown for that offline provider—not an
estimate of a live multi-agent bill.

The separate recorded Gemini boundary test made three single-reasoner requests and the provider
reported 1,058 input plus 531 output tokens. That is evidence that the provider integration worked
for those three synthetic cases only; it is not a multi-agent cost sample.

The live multi-agent runner records every role invocation and the end-to-end envelope across 10
tasks and three trials. Its report keeps per-agent latency, input/output tokens, model calls, tool
calls and end-to-end totals. Per-agent and total dollar cost remain `null` unless both provider
prices are explicitly configured. The first 30-trial run completed on 2026-10-01 with 35,592 input
tokens, 9,008 output tokens, 65 model calls, 16 tool calls, 2.13-second p50 and 8.79-second p95
end-to-end latency. All 30 trials failed the strict gate: seven violated an evidence/policy output
contract and 23 ended in provider failure. Dollar cost remains `null` because pricing was not
configured. These are failure-envelope measurements, not a model-quality success result.

A separate saved provider-backed trace completed one difficult case through supervisor,
investigation, policy, resolution and critic roles in 8.07 seconds. It used seven model calls, two
read tools, 5,598 input tokens and 1,424 output tokens. It proves that the integrated path can reach
the deterministic control plane; one passing trace does not override the failed 30-trial sample.

## Runtime controls

`RESOLVEOPS_AGENT_INPUT_COST_PER_MILLION_USD` and
`RESOLVEOPS_AGENT_OUTPUT_COST_PER_MILLION_USD` must be configured together. Only then does the
runtime calculate an estimated cost from observed tokens. `RESOLVEOPS_AGENT_COST_LIMIT_USD` adds a
hard workflow budget. Model calls, tool calls, agent steps, input/output tokens, wall time, tool-loop
turns, and replans have independent bounds. Analysis is operator-triggered and never starts merely
because a page opened.

## Infrastructure cost surfaces

The local SQLite demo is free apart from the user's machine. Local Docker uses the same machine.
The AWS reference would bill for an ALB, NAT gateway/public IPv4, ECS Fargate API and worker tasks,
RDS PostgreSQL, ElastiCache Valkey, ECR, CloudWatch, backups, and data transfer. Multi-AZ settings
increase resilience and cost. No monthly total is stated because no account, region-specific plan,
traffic profile, uptime schedule, or deployed bill exists.

## Cost tradeoffs

- Five-role analysis uses materially more calls than the single advisory reasoner, so it is optional.
- Investigation and policy can run concurrently to reduce elapsed latency, not token totals.
- Reviewed memory is small, scoped context; it never replaces current evidence or policy.
- The cross-encoder reranker was rejected because its small quality gain added about 1.13 seconds to
  local p95.
- In-process exact retrieval remains appropriate for 17 policy chunks; pgvector is the measured
  scale-up path rather than a current always-on dependency.
- Redis/Valkey is coordination only. PostgreSQL durability prevents cache loss from becoming job
  loss, but a managed cache still adds operational cost.

Before any paid launch, run a staging sample with the chosen model, explicit prices, realistic
traffic, and the actual cloud plan. Store observed calls, tokens, latency, and billing separately
from estimates.
