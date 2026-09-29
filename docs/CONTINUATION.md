# ResolveOps continuation point

Last verified: 2026-09-28

## Current state

- Branch: `codex-build`
- Packets 0 through 15 are complete. Packet 16's deployment foundation is implemented and fully
  verified locally, but the live AWS launch is still pending.
- Packet 16 implementation includes a non-root multi-stage image, migration-gated Docker Compose stack,
  liveness and schema-aware readiness, CI and manual AWS deployment workflows, immutable image
  rollout, one-shot ECS migrations, deployment verification, AWS Terraform, monitoring, rollback
  guidance, cost/resilience limitations, and deployment documentation are implemented.
- The security architecture deliberately uses one database per tenant. Packet 13 therefore requires
  no domain-table tenant migration; every tenant database receives the existing migrations.
- The implementation is committed and pushed to the private GitHub `codex-build` branch.
- No real OpenAI API call or cloud connection has been made.
- No AWS resources were created and no cloud credentials were used.
- Packet 16's temporary Compose stack, PostgreSQL test container, database volumes, and local test
  image were removed after verification.
- The real read-only operator console is implemented at `/console`. It reads authenticated simulator
  data and protected Prometheus metrics, keeps the bearer key only in browser memory, and has
  responsive Overview, Customer Ops, Employee/IT, and Reliability views.

## Last verified results

- Full local suite: 160 passed, 1 skipped.
- Packet 13 adversarial security suite: 17 passed.
- Real PostgreSQL integration: 1 passed, 142 deselected, including Employee/IT execution.
- Workflow evaluation: 24 of 24 cases passed.
- Employee/IT workflow evaluation: 14 of 14 cases passed.
- Local performance measurement: 72 of 72 evaluations passed across three measured runs after one
  warm-up. Workflow p50 was 19.292 ms and p95 was 34.924 ms; hybrid retrieval p50 was 3.641 ms and
  p95 was 5.079 ms on the recorded workstation environment.
- Migration upgrade, complete downgrade, and second upgrade: passed on PostgreSQL 16.
- Ruff: passed.
- Docker image build: passed.
- Docker Compose migration, health, repeatable seed, non-root/read-only controls, and external
  deployment verification: passed.
- Terraform 1.10.5 initialization, formatting, and validation with AWS provider 6.66.0: passed.
- GitHub Actions static validation with actionlint 1.7.12: passed.
- Mypy: passed across 115 source files.
- Dependency check: passed.
- Bandit medium/high scan: passed with no findings.
- Installed dependency audit: passed with no known vulnerabilities after updating the local virtual
  environment's `pip` installer to 26.2.1.
- Publishable-file credential-pattern scan: passed. `.env` is ignored and untracked.
- GitHub remote verification passed; `codex-build` now tracks the private origin branch.
- GitHub-hosted CI passed on commit `2606fb0`: Quality, Security, PostgreSQL, Container, and
  Terraform jobs all completed successfully.
- One understood third-party Starlette deprecation warning remains.

## Packet 13 decisions to preserve

- An authenticated identity supplies its subject, tenant, and role; request input never chooses
  tenant or role.
- Every simulator API database session comes from the authenticated tenant registry.
- Agents can read operational data but receive masked PII; Operator, Approver, and System roles have
  the explicit `read_pii` permission.
- Multi-tenant webhooks require a different HMAC secret per tenant.
- Policy content is validated before chunking, embedding, or storage. Retrieved evidence and policy
  remain untrusted data, and LLM output remains advisory.
- Authentication and tenant-denial audits never store presented secrets.

## Packet 14 decisions to preserve

- Trace attributes must not contain customer PII, evidence, policy text, prompts, model outputs,
  credentials, raw request bodies, or exception messages.
- A child tool or model failure is not automatically a failed workflow; final-state correctness
  remains an evaluation result.
- Percentiles are calculated only from observed samples using nearest-rank selection.
- Token usage is recorded only when the provider reports it. Cost remains null unless a real call
  and explicit reviewed pricing are both available.
- The checked-in SQLite/offline benchmark is a local regression baseline, not a production SLO,
  throughput claim, or cloud benchmark.

## Packet 15 decisions to preserve

- Directory, Git, ticket, and notification integrations are enterprise-system simulators. Do not
  describe them as live GitHub, identity-provider, or vendor integrations.
- Repository access requires active employment, an active owned identity, MFA, active target-team
  membership, an active linked Git account, repository/team mapping, an action-pending case, and
  exact approval by the target-team manager.
- LLM reasoning remains optional and advisory. It cannot approve, grant, or verify access.
- Partial or conflicting existing access escalates. Exact existing access returns a no-action result
  and creates no duplicate operation.
- One controlled action creates the missing group membership and repository access, fulfills the
  request, resolves the case and ticket, and sends the notification. Success requires a fresh read
  that verifies every final record.
- Employee and identity reads use the existing tenant boundary. Agents receive masked employee PII,
  enterprise usernames, Git usernames, and notification recipients.
- The stored manager approval is an input to Packet 15; this packet does not add a second durable
  human-approval pause for the same decision.

## Packet 16 decisions to preserve

- Liveness has no database dependency. Readiness checks every configured tenant database and the
  exact Alembic head revision without exposing database errors or tenant identifiers.
- Containers run as user 10001. Compose and ECS use a read-only application filesystem; Compose also
  drops all capabilities and enables no-new-privileges.
- Migrations are one-shot tasks and must succeed before a new API task definition is deployed.
- AWS images use immutable Git commit SHA tags. GitHub Actions uses OIDC, not long-lived AWS keys.
- Terraform creates the application infrastructure but deliberately does not bootstrap its own
  state bucket, lock table, GitHub OIDC trust, or application secret. Those account-level resources
  require the user's cloud-account choices and authorization.
- The default AWS design uses private ECS/RDS subnets, one NAT gateway, encrypted non-public RDS,
  RDS-managed credentials, Secrets Manager injection, ALB health checks, CloudWatch alarms, and RDS
  deletion protection. The single NAT and default single-AZ database are documented cost/resilience
  tradeoffs, not production SLO claims.
- Terraform ignores ECS service task-definition and desired-count drift because the deployment
  workflow owns those fields after a successful migration.
- No real AWS deployment may be claimed until the public service and account resources are actually
  created and verified.

## Operator console decisions to preserve

- The console is a read-only operator demonstration. Do not add browser write controls that bypass
  the internal authorization, approval, idempotency, audit, and verification layer.
- Business data must come from authenticated simulator APIs. Do not replace protected reads with
  hard-coded success cards or imply that synthetic records are live vendor integrations.
- Keep the bearer key in page memory only. Never place it in browser storage, URLs, rendered records,
  screenshots, traces, metrics, or checked-in configuration.
- Keep UI assets same-origin with a restrictive Content Security Policy and no third-party browser
  dependencies unless a later security review explicitly changes this decision.

## Current completion plan

The user does not want paid infrastructure. Keep the validated AWS Terraform and deployment
workflow as reference architecture, but do not create AWS resources. Finish the portfolio in this
order:

1. deploy the working demonstration with free Render compute and free Supabase PostgreSQL;
2. run the controlled cloud workload, analyze real failures, and rerun regressions; and
3. finish the recruiter README, screenshots, walkthrough, ADRs, interview notes, public release,
   and profile pin.

The free-tier Gemini proof is complete. On 2026-09-28, `gemini-3.5-flash-lite` passed all 3 synthetic
cases with 1,589 provider-reported tokens and a 4.74-second median observed latency (1.49-6.77
second range). The artifact is `evals/reasoning/gemini-live-report.json`. Treat these values only as
the observed result of this small run, never as a production SLO or broad model-quality claim.

The API protection and Prometheus packet is also complete locally. Every request has a 1 MiB default
body limit, and non-health traffic uses a bounded token bucket keyed by both network identity and a
digest of the presented credential. Operations roles can scrape bounded-label metrics at `/metrics`.
The complete suite now passes 156 tests with 1 intentionally skipped PostgreSQL environment test;
Docker Compose configuration, the rebuilt image, lint, formatting, strict typing, and dependency
checks also pass. The limiter and counters are intentionally process-local for the single-worker
portfolio container; scaled deployment requires shared gateway or datastore enforcement.

The operator-console packet is complete locally. The interface is served by FastAPI with local
assets only, performs authenticated reads without browser credential persistence, and passed live
synthetic-data checks at desktop and 390-pixel mobile widths. It does not expose write controls or
pretend that simulator records are live vendor integrations. See `docs/OPERATOR_CONSOLE.md`.

The repository security and GitHub-readiness packet is complete locally. CI now has a dedicated
security job, pinned third-party Action revisions, and Dependabot coverage. Local Actionlint,
Compose, Terraform, credential, Bandit, dependency, evaluation, and test gates pass. The corrected
local `.env` remains ignored and untracked. The reviewed work was committed and pushed only after
explicit user authorization. The first hosted run exposed a Linux-only test import issue; commit
`2606fb0` fixed the package boundary, and the complete hosted CI matrix then passed.

## Safety rules to preserve

- LLM output is advisory and cannot execute actions.
- Authorization, approval limits, idempotency, state transitions, financial rules, and final verification remain deterministic.
- A refund request is never considered complete merely because a tool returns success.
- Do not auto-commit.

## Resume instruction

Tell Codex: `Continue ResolveOps completion plan from docs/CONTINUATION.md.`
