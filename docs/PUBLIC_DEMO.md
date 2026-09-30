# Safe public demo runbook

ResolveOps includes a validated Render Blueprint and a live synthetic public demo. AWS Terraform
remains reference infrastructure unless an AWS deployment is actually completed.

## Free Render deployment

The root `render.yaml` provisions one free Docker web service and one dedicated free PostgreSQL 16
database in the Ohio region. Render generates the session and webhook secrets; no provider key is
requested or stored. On every service start, the container runs forward migrations, idempotently
loads the fictional baseline, and starts the API on Render's assigned port. Auto-deployment waits
for GitHub checks to pass.

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
- `RESOLVEOPS_INTEGRATED_AGENTS_ENABLED=false` until the exposed provider key is rotated

The Blueprint runs migrations and the synthetic seed automatically. After Render reports the deploy
as live, verify `/health/live`, `/health/ready`, `/console`, demo-session isolation, reset behavior,
rate limits, and absence of secrets in responses and logs.
Run `scripts/verify_deployment.py --base-url https://your-demo-host` and store its output with the
deployment date, host, image revision and region. Keep deployed latency separately from local
measurements.

## Deployment record

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

The current public link was published only after the deployment verifier and the console workflow
checks above passed against the Render URL.
