# PostgreSQL scale procedure

1. Create an isolated database whose name contains `benchmark`.
2. Run `scripts/run_scale_benchmark.py` with an explicit URL and increasing sizes practical for
   the machine.
3. Preserve the result JSON unchanged.
4. Inspect query plans for any materially slower query.
5. If an index is changed, record the plan, before result, change, after result, and tradeoff.

The runner measures generation/load time, exact generated and loaded counts, PostgreSQL database
bytes, p50/p95/max query latency, hybrid retrieval latency, runner CPU time, and traced Python
memory. It does not pretend that direct query latency is HTTP latency or that runner memory is
PostgreSQL server memory.
