# Local performance artifacts

`customer_operations_local.json` is produced by the reproducible command documented in
`docs/OBSERVABILITY.md`. It records the machine/runtime description, dataset fingerprint, warm-up
and measured run counts, evaluation result, component latency distributions, retry counts, and
token/cost availability.

The artifact is a local regression baseline. It is not a production SLO, scale result, throughput
claim, or cloud benchmark. Rerunning the command may change latency values because workstation load
is not controlled; preserve the generated timestamp and environment when comparing results.
