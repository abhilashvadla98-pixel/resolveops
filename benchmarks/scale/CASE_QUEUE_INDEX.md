# Case queue index: measured decision record

## Problem

The operator console sorts the case queue by the most recently updated case. At 10,000 customer
cases, PostgreSQL used a sequential scan followed by a top-N sort. The isolated benchmark measured
case-list latency at 5.899 ms p50 and 7.455 ms p95.

## Evidence before the change

`EXPLAIN (ANALYZE, BUFFERS)` on the exact queue query showed a sequential scan and top-N heapsort.
The measured execution time for the inspected plan was 11.903 ms. The complete three-size run is
preserved in `benchmarks/results/scale-before-case-index-2026-09-29.json`.

## Change

Migration `0013_case_queue_updated_index.py` adds an index on `cases.updated_at`. The application
model declares the same index so migration drift checks keep the schema honest. PostgreSQL can scan
the index backward for the descending queue without maintaining a second direction-specific index.

## Evidence after the change

The same inspected plan changed to a backward index scan and completed in 0.035 ms. The full
benchmark is preserved in `benchmarks/results/scale-after-case-index-2026-09-29.json`.

| Customer cases | Generated records | Before p50 | Before p95 | After p50 | After p95 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 100 | 1,523 | 3.361 ms | 3.980 ms | 3.145 ms | 3.788 ms |
| 1,000 | 15,178 | 4.993 ms | 6.228 ms | 3.233 ms | 4.865 ms |
| 10,000 | 151,862 | 5.899 ms | 7.455 ms | 3.510 ms | 4.090 ms |

## Tradeoff and limits

The index consumes storage and adds maintenance work to case writes. At the largest point, database
size increased from 48,357,903 to 49,390,095 bytes. Load time changed from 34.988 to 34.460 seconds,
but that small improvement is treated as measurement noise, not a write-performance claim. These
are local, direct-query, synthetic measurements; they do not establish production capacity.
