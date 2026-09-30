# ResolveOps operations runbook

This runbook covers the checked-in API, worker, PostgreSQL, and Redis/Valkey design. Commands and
resource names must be reviewed for the target environment. No public deployment is claimed.

## Release gate

Before a release, require a green CI revision, immutable image SHA, reviewed Terraform plan, current
backup, migration compatibility review, and an approved rollback task definition. Apply
infrastructure with both services at zero, run the one-shot migration, then deploy the worker and
API. Verify ECS stability, target health, `/health/ready`, logs, queue health, and one synthetic
read-only business flow. Do not use a production write as a smoke test.

Schema changes should be expand/contract compatible with the previous API and worker revision.
Never automatically downgrade a database after new code has written data.

## Queue backlog

Signal: `resolveops_agent_queue_jobs{status="pending|retrying"}` rises and stays above the normal
environment baseline.

1. Check API and worker task counts, worker logs, PostgreSQL readiness, Valkey reachability, and
   provider health.
2. Confirm workers are claiming jobs and their leases move forward. Do not delete pending jobs.
3. If the provider is healthy and the database is not saturated, increase workers within the
   reviewed capacity limit. More workers increase provider calls and cost.
4. If the provider is degraded, stop new submissions or return controlled backpressure; let durable
   jobs remain in PostgreSQL.
5. After recovery, confirm backlog returns to baseline and sample completed job event histories.

## Expired lease or stopped worker

Workers recover expired leases before claiming new work. Confirm the original worker is gone, wait
for the configured lease to expire, then start a healthy worker. Check for a `retry_scheduled` event
with `worker_lease_expired`. The attempt cap must eventually complete or dead-letter the job; never
manually reset attempts to create an unbounded loop.

## Dead-letter jobs

Inspect the job's persisted event sequence, error classification, agent runs, tool calls, trace ID,
and provider status. Fix the underlying fault first. There is no blind bulk replay command. A
reviewed replay must use a new idempotency key while preserving the original audit history and must
remain inside normal model/tool/action budgets.

## Valkey outage

PostgreSQL remains the job source of truth. API enqueue commits the job before sending a wake-up;
workers continue polling if wake-up fails. The HTTP rate limiter falls back to a bounded local
bucket, which weakens cross-replica quota consistency. Keep serving only if the local limits and
gateway controls are acceptable; otherwise reduce traffic. Restore Valkey, verify TLS connectivity,
then confirm wake-ups and shared rate limits without flushing PostgreSQL jobs.

## Provider outage or budget stop

Provider failures are classified and bounded. Do not bypass model-call, token, wall-clock, or cost
limits. Pause submissions if retries would amplify the outage. Deterministic customer/IT control
flows remain separate from advisory multi-agent reasoning; do not represent a failed advisory run
as a completed business action.

## Migration failure

The deployment workflow stops before updating services. Preserve the failed task logs and migration
revision. If the migration transaction rolled back, keep the prior services. If it partially changed
state, follow a reviewed forward fix; do not run an automatic downgrade. Rehearse repair on a restored
copy before touching production data.

## Application rollback

Select the last known-good immutable task definitions that are compatible with the current schema.
Stop new agent submissions, allow active worker leases to finish, update the worker and API services,
wait for both to stabilize, and verify readiness plus queue health. ECS circuit breakers cover failed
service deployment, not logical data incompatibility.

## Backup and restore

Use managed RDS backups and point-in-time recovery for the deployed environment. The repository's
guarded logical drill is additional evidence only. Restore into an isolated database, validate the
Alembic revision and business/agent durability tables, then run integrity and smoke checks before a
controlled cutover. Record actual recovery-point and recovery-time observations; no RPO/RTO is
claimed until that exercise occurs in the target environment.

## Initial service objectives

These are proposed alerting objectives, not measured production results:

- availability: readiness success and healthy target count, excluding approved maintenance;
- safety: zero cross-tenant reads and zero action execution without deterministic authorization;
- durability: zero duplicate queue claims and zero duplicate side effects for one idempotency key;
- backlog: alert on sustained growth relative to arrival rate, not a universal hard-coded count;
- latency: establish API and agent p95 objectives only after staging traffic measurements;
- recovery: establish RPO/RTO only after a managed-backup restore drill.

Every incident record should include time range, affected tenant scope, trace/job/workflow IDs,
customer impact, containment, recovery evidence, and the regression or runbook change that follows.
