# Safe public demo runbook

ResolveOps is ready to package for a synthetic public demo, but this repository does not claim that
one is deployed. The owner must choose and authorize a hosting account. AWS Terraform remains
reference infrastructure unless an AWS deployment is actually completed.

## Required public-demo configuration

- `RESOLVEOPS_ENVIRONMENT=demo`
- a managed PostgreSQL URL dedicated to `TENANT-DEMO`
- `RESOLVEOPS_DEFAULT_TENANT_ID=TENANT-DEMO`
- `RESOLVEOPS_DEMO_ENABLED=true`
- a new random demo-session secret of at least 32 characters
- a new random webhook secret of at least 32 characters
- no real customer, employee, payment, identity or repository data
- `RESOLVEOPS_INTEGRATED_AGENTS_ENABLED=false` until the exposed provider key is rotated

Run migrations and the synthetic seed once, then verify `/health/live`, `/health/ready`, `/console`,
demo-session isolation, reset behavior, rate limits, and absence of secrets in responses and logs.
Run `scripts/verify_deployment.py --base-url https://your-demo-host` and store its output with the
deployment date, host, image revision and region. Keep deployed latency separately from local
measurements.

## Release boundary

The public visitor path should use deterministic seeded cases and must not spend provider quota on
page load. If live integrated agents are later enabled, require the rotated credential, strict call
budgets, synthetic cases only and visible quota-failure handling. Never put the key in browser code,
the image, repository variables visible to forks, screenshots or videos.

Do not publish a “Live Demo” link until the deployment verifier passes against the public URL.
