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

## Not measured yet

- PostgreSQL workflow latency;
- external embedding or model latency;
- production API latency;
- concurrent throughput and saturation;
- cold-start and deployment startup time;
- memory and CPU consumption;
- provider token cost or cost per workflow; and
- production p50/p95 or SLO compliance.
