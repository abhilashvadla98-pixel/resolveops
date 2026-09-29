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

## Not measured yet

- PostgreSQL workflow latency;
- external embedding or model latency;
- production API latency;
- mutation/approval throughput and a controlled capacity curve below and above saturation;
- cold-start and deployment startup time;
- full server and PostgreSQL memory/CPU consumption;
- provider token cost or cost per workflow; and
- production p50/p95 or SLO compliance.
