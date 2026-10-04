# Safe public demo runbook

ResolveOps includes a validated Render Blueprint and a live synthetic public demo. AWS Terraform
remains reference infrastructure unless an AWS deployment is actually completed.

## Free Render deployment

The root `render.yaml` provisions one free Docker web service and one dedicated free PostgreSQL 16
database in the Ohio region. Render generates the session and webhook secrets; no provider key is
requested or stored. On every service start, the container runs forward migrations, idempotently
loads the fictional baseline, and starts the API on Render's assigned port. The Blueprint requests
deployment after GitHub checks pass. For the October 4 release, no automatic deployment appeared;
the owner authorized a manual deployment after all checks passed. No billing or plan change was made.

Each signed visitor receives a separate PostgreSQL schema populated with the same synthetic
baseline. Reset changes only that visitor's schema. Expired workspaces are removed before new ones
are created, and the service rejects new sessions safely when the configured workspace limit is
reached. This keeps simultaneous walkthroughs from changing one another's cases or approvals.

[Create the ResolveOps demo from the Blueprint](https://dashboard.render.com/blueprints/new?repo=https%3A%2F%2Fgithub.com%2Fabhilashvadla98-pixel%2Fresolveops)

The account owner must review and approve resource creation in Render. Select only the `free` plan
shown by the Blueprint. Do not add a payment method merely to deploy this demo. Free web services
sleep after inactivity and can take about one minute to wake. Render's free PostgreSQL database
expires after 30 days, so treat this as a public demonstration rather than durable production
infrastructure.

## Required public-demo configuration

- `RESOLVEOPS_ENVIRONMENT=demo`
- a managed PostgreSQL URL dedicated to `TENANT-DEMO`
- `RESOLVEOPS_DEFAULT_TENANT_ID=TENANT-DEMO`
- `RESOLVEOPS_DEMO_ENABLED=true`
- a new random demo-session secret of at least 32 characters
- `RESOLVEOPS_DEMO_ISOLATED_SESSIONS=true`
- a bounded `RESOLVEOPS_DEMO_MAX_ISOLATED_SESSIONS` value
- a new random webhook secret of at least 32 characters
- no real customer, employee, payment, identity or repository data
- `RESOLVEOPS_INTEGRATED_AGENTS_ENABLED=false`; rotation alone is not sufficient to enable public inference

The Blueprint runs migrations and the synthetic seed automatically. After Render reports the deploy
as live, verify `/health/live`, `/health/ready`, `/console`, demo-session isolation, reset behavior,
rate limits, and absence of secrets in responses and logs.
Run `scripts/verify_deployment.py --base-url https://your-demo-host` and store its output with the
deployment date, host, image revision and region. Keep deployed latency separately from local
measurements.

## Verified deployment — October 4, v1.2.0

- Public URL: [ResolveOps console](https://resolveops-demo.onrender.com/console)
- Release commit: `020ef9d2ecd6311d7b99f73d9030c6fb0fbe5aac`
- `/health/build`: version `1.2.0`, schema `0023_refund_lifecycle_states`, exact commit above
- `/health/ready`: `ready`; Render dashboard showed **Deploy succeeded | Live**
- Deployment: owner-authorized manual deployment, completed in 2 minutes 10 seconds
- Verification time: 2026-10-04 at 05:42 UTC; separate signed, isolated synthetic workspace
- Customer success: new complaint → investigation → approval → pending refund → simulated
  completed settlement → fresh refund, workflow and resolved-case reads
- Customer failure: separate new complaint → approval → pending refund → simulated failed
  settlement → fresh reads report review/escalation, not a resolved case
- Employee: new request → explicitly simulated manager approval → processing → fresh active
  repository-access and resolved-case reads
- Inference: metadata and both customer runs reported `rules_only`; no model-run records appeared
- Measured total: 13.61 seconds for this sequential API verification run. The first case request
  took 5.33 seconds, including first access to the isolated workspace. This is a single deployed
  observation, not an SLO or a local benchmark. Free-instance cold start was not measured.
- Browser check: the public console loaded seven customer cases, four employee requests and
  one pending approval, with **Service healthy** visible

The [secret-free deployed report](https://github.com/abhilashvadla98-pixel/resolveops/releases/download/v1.2.0/public-workflow-verification-20261004T054258Z-87f00bed.json)
records each request status and duration, result identifiers, build identity and synthetic mode.
No bearer token is stored. It is separate from the local live-model evaluation and rules-only video.

## Historical deployment record — September 30

This record predates the October 4 lifecycle and authorization repairs. It is not proof that the
current release is deployed. New verification must identify the exact `/health/build` commit,
migration readiness and fresh isolated workflow results separately from these measurements.

- Public URL: https://resolveops-demo.onrender.com/console
- Host and region: Render, Ohio
- Application revision: `c102f4a076cc61547c6c802e2afa998220098125`
- Deployment date: 2026-09-30
- External verification: `/health/live`, `/health/ready`, and `/openapi.json` returned HTTP 200;
  the isolated workspace loaded the seeded customer and IT queues; approval, controlled execution,
  fresh-state verification, and baseline reset completed through the public console
- Session-isolation verification: two independently signed visitor sessions loaded the same baseline;
  a synthetic case created in the first session remained visible there and was absent from the second
- Warm console latency after the latest deployment: five samples of 158.5, 188.9, 108.5,
  267.9, and 192.4 ms; median 188.9 ms
- Warm workspace preparation: session creation 253 ms, deterministic baseline reset 2,086 ms,
  and individual queue/approval/audit requests 201-397 ms
- Cold-start measurement: not measured during this deployment; Render warns that a sleeping free
  service can take 50 seconds or more to wake. The console now shows explicit startup progress and
  allows 90 seconds for the free service to resume instead of failing after 15 seconds.
- Persistence limitation: the free PostgreSQL database expires after 30 days and must be replaced
  or upgraded to keep the public demo available

## Release boundary

The public visitor path should use deterministic seeded cases and must not spend provider quota on
page load. If live integrated agents are later enabled, require the rotated credential, strict call
budgets, synthetic cases only and visible quota-failure handling. Never put the key in browser code,
the image, repository variables visible to forks, screenshots or videos.

The original public link was published after those checks. They are historical evidence, not a
substitute for testing each new release.
