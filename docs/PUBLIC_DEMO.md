# Safe public demo runbook

ResolveOps includes a validated Render Blueprint for a synthetic public demo, but this document does
not claim that the public URL is live until the deployment record below is completed. AWS Terraform
remains reference infrastructure unless an AWS deployment is actually completed.

## Free Render deployment

The root `render.yaml` provisions one free Docker web service and one dedicated free PostgreSQL 16
database in the Ohio region. Render generates the session and webhook secrets; no provider key is
requested or stored. On every service start, the container runs forward migrations, idempotently
loads the fictional baseline, and starts the API on Render's assigned port. Auto-deployment waits
for GitHub checks to pass.

[Create the ResolveOps demo from the Blueprint](https://dashboard.render.com/blueprints/new?repo=https%3A%2F%2Fgithub.com%2Fabhilashvadla98-pixel%2Fresolveops)

The account owner must review and approve resource creation in Render. Select only the `free` plan
shown by the Blueprint. Do not add a payment method merely to deploy this demo. Free web services
sleep after inactivity and can take about one minute to wake. Render's free PostgreSQL database
expires after 30 days, so treat this as a recruiter demonstration rather than durable production
infrastructure.

## Required public-demo configuration

- `RESOLVEOPS_ENVIRONMENT=demo`
- a managed PostgreSQL URL dedicated to `TENANT-DEMO`
- `RESOLVEOPS_DEFAULT_TENANT_ID=TENANT-DEMO`
- `RESOLVEOPS_DEMO_ENABLED=true`
- a new random demo-session secret of at least 32 characters
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

Complete this only with measured public results:

- Public URL: pending
- Host and region: Render, Ohio
- Git revision: pending
- Deployment date: pending
- External verification: pending
- Cold-start measurement: pending

## Release boundary

The public visitor path should use deterministic seeded cases and must not spend provider quota on
page load. If live integrated agents are later enabled, require the rotated credential, strict call
budgets, synthetic cases only and visible quota-failure handling. Never put the key in browser code,
the image, repository variables visible to forks, screenshots or videos.

Do not publish a “Live Demo” link until the deployment verifier passes against the public URL.
