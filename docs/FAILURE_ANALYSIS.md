# ResolveOps failure analysis

## What the measured run observed

The 72-workflow local measurement completed with 72 correct evaluation results and no unhandled
workflow failures. This does not mean every child operation succeeded. The dataset deliberately
contains denial, validation, provider-timeout, verification, policy, and reasoning failures.

- The issue-refund tool ran 42 times and 27 spans ended with an exception. These include expected,
  deterministic denials and invalid-action cases as well as simulated tool failures. The workflow
  caught them and produced the expected review or waiting state.
- Six retry events were scheduled: three execution retries and three verification retries. Retries
  remained bounded and reused the same idempotency control.
- Fifteen bounded reasoning calls ran; six failed as designed. Three used the scripted provider
  failure and three returned intentionally invalid citations that grounding validation rejected.
- Final outcomes were 12 `action_verified`, 51 `needs_review`, and 9 `waiting_external`. These counts
  describe the dataset paths and are not a production success-rate estimate.

## Findings

No unexpected correctness failure appeared in this run. The trace model correctly separates a
child-component error from final workflow correctness. Operational alerts should therefore classify
known authorization and business-rule exceptions separately from unexpected provider or system
errors instead of treating every tool exception as an incident.

The latency maxima were isolated outliers relative to p95. There is not enough evidence to assign a
root cause. A future investigation should repeat the workload on PostgreSQL under controlled CPU and
memory conditions, capture system-resource metrics, and profile only if the outlier is reproducible.

## Safety and privacy review

Trace tests confirm that exception messages are not recorded. Current spans contain identifiers,
route templates, role/model/provider names, counts, statuses, and timing only. Any future telemetry
attribute must be reviewed before addition; customer data, evidence, policy excerpts, prompts,
outputs, credentials, and raw request bodies remain prohibited.

## Failures found during the data and scale pass

### Invalid authorization-hold refund histories

A 100-case generated dataset failed two quality checks because authorization-hold payments entered
the resolved refund path even though no charge had been captured. The defect was in the generator,
not the validator. The generator now excludes authorization holds from that path, and the same
twelve-check validation completes with zero failures. No invalid dataset was loaded.

### Case queue sequential scan

The 10,000-case PostgreSQL query plan showed a sequential scan and top-N sort for the operator
queue. This was a reproducible data-size problem, so an `updated_at` index was added through an
Alembic migration and model metadata. The inspected execution changed from 11.903 ms to 0.035 ms;
repeated queue p95 changed from 7.455 ms to 4.090 ms. The extra index storage and write maintenance
are documented rather than treated as free.

### Rate-limit saturation

The first unpaced API run generated far more traffic than the configured boundary: 15,355 requests
in 30 seconds, with 15,177 rejected/failed requests. This did not measure ordinary application
capacity. The runner was changed to support an explicit target rate, and a 1.5 requests/second
follow-up completed all 90 requests successfully. Future capacity work must classify status codes,
measure the server and database, and test controlled rate steps rather than equating rate limiting
with backend failure.
