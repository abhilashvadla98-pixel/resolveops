# ResolveOps measured performance

## Local workflow baseline

Measurement artifact: `evals/performance/customer_operations_local.json`

The checked-in baseline was measured on 2026-09-27 using CPython 3.12.10 on Windows 11. It used one
warm-up run followed by three measured runs of the 24-case workflow dataset: 72 measured workflows.
All 72 evaluation executions passed their deterministic final-state assertions.

| Signal | Samples | Minimum | p50 | p95 | Maximum |
| --- | ---: | ---: | ---: | ---: | ---: |
| End-to-end workflow | 72 | 12.622 ms | 19.292 ms | 34.924 ms | 174.106 ms |
| Hybrid retrieval | 72 | 3.182 ms | 3.641 ms | 5.079 ms | 164.182 ms |
| Load-case node | 72 | 4.592 ms | 5.627 ms | 7.413 ms | 117.045 ms |
| Execute-refund node | 42 | 3.454 ms | 9.048 ms | 13.950 ms | 20.232 ms |
| Issue-refund tool | 42 | 3.421 ms | 8.987 ms | 13.596 ms | 19.861 ms |

These are observed local values, not targets or guarantees. Full precision and every measured
operation are preserved in the JSON artifact. The p50/p95 values use nearest-rank selection rather
than interpolation.

## Interpretation

Normal p95 workflow latency in this offline sample was 34.924 ms. Retrieval and controlled refund
execution were the largest regularly observed components. A few maximum values were much larger
than their p95 values: retrieval reached 164.182 ms and load-case reached 117.045 ms. The sample is
too small and the desktop environment too uncontrolled to identify their cause. They may reflect
host scheduling, SQLite behavior, or runtime pauses. ResolveOps does not claim a performance fix
without a controlled reproduction and profiler evidence.

The benchmark recorded 732 trace events and six scheduled retries across the 72 workflows. Token
usage and cost are null because the benchmark used an offline scripted reasoner and made no paid
model call.

## Isolated PostgreSQL scale run

On 2026-09-29, the scale runner generated, validated, and loaded three deterministic datasets into
an isolated database named `resolveops_benchmark`. The temporary PostgreSQL container was removed
after the run. The largest completed point was 151,862 records: 10,000 customer cases and 2,500 IT
requests.

| Customer cases | IT requests | Records | Generate | Load | Database bytes |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 100 | 25 | 1,523 | 0.324 s | 0.567 s | 13,761,559 |
| 1,000 | 250 | 15,178 | 1.504 s | 3.504 s | 17,472,535 |
| 10,000 | 2,500 | 151,862 | 10.577 s | 34.460 s | 49,390,095 |

At 10,000 cases, an `updated_at` index improved case-queue p95 from 7.455 ms to 4.090 ms. The
inspected PostgreSQL plan changed from a sequential scan plus top-N sort at 11.903 ms to a backward
index scan at 0.035 ms. Full artifacts and the storage/write tradeoff are in
`benchmarks/results/` and `benchmarks/scale/CASE_QUEUE_INDEX.md`.

These numbers are direct-query results on one developer machine. Runner memory excludes the
PostgreSQL server, and synthetic data does not establish production capacity.

## Bounded API soak and saturation

The read-only API runner exercised seven queue, detail, timeline, audit, approval, IT, and
reliability routes. A paced 60.58-second run made 90 requests at 1.486 requests/second. All 90
returned HTTP 200; client-observed latency was 16 ms p50 and 47 ms p95.

An earlier unpaced six-worker run attempted 15,355 requests in 30 seconds and recorded 15,177
errors after exceeding the configured application rate limit. It is retained as rate-protection
evidence, not as an application-capacity result. Mutation endpoints were excluded from both runs.

A separate 30.38-second isolated mixed run combined the same operational reads with resettable case
intake writes. Four clients targeted 8 requests/second and completed 232 requests (30 case writes,
12.93% of traffic) with zero errors. Client-observed latency was 16 ms p50 and 47 ms p95; case
intake was 16 ms p50 and 156 ms p95. Server RSS grew by 13.8 MB between the start and end samples.
That start/end signal did not show unbounded growth in this short run, but it is not a leak proof.
The exact operation counts and limitations are stored in
`benchmarks/results/load-mixed-soak-2026-09-29.json`.

## Durable queue concurrency

A disposable PostgreSQL 16 run enqueued 200 jobs and used eight concurrent workers to claim them.
All 200 jobs were claimed exactly once: zero duplicates and zero missing claims. Enqueue throughput
was 156.13 jobs/second, claim throughput was 426.44 jobs/second, and claim latency was 16 ms p50 / 32
ms p95. The runner removes only its own benchmark jobs afterward. It does not invoke a model, so
this is queue-coordination evidence rather than agent-provider capacity. See
`benchmarks/results/agent-queue-2026-09-29.json`.

## Not measured yet

- PostgreSQL workflow latency;
- external embedding or model latency;
- production API latency;
- approval/action throughput and a controlled capacity curve below and above saturation;
- a multi-hour soak with continuous process, database, Redis, and host resource telemetry;
- cold-start and deployment startup time;
- full server and PostgreSQL memory/CPU consumption;
- provider token cost or cost per workflow; and
- production p50/p95 or SLO compliance.

## Retrieval serving decision

A separate disposable-container benchmark now covers exact vector serving at 1,000 and 10,000
synthetic vectors. At 10,000 vectors, Python exact cosine measured 363.24 ms p95 and pgvector exact
cosine measured 8.02 ms p95 with full top-five agreement over 12 queries. ResolveOps retains the
in-process exact implementation for the actual 17-chunk corpus and records pgvector as the measured
scale-up option rather than adding an unused production dependency. See
`benchmarks/results/vector-serving.json` for environment and limitations.
