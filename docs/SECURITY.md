# ResolveOps security model

## Security boundary

ResolveOps treats API credentials, tenant routing, authorization, and action controls as server-side
decisions. A client cannot select its role or database. The authenticated API-key identity supplies
the subject, tenant, and role. Simulator routes then open only that tenant's configured database.

`/health` and the generated API schema remain public for local operations. Every
`/simulator/v1/*` route requires `Authorization: Bearer <api-key>`. Refund-status webhooks use their
own HMAC authentication contract instead of API keys.

## Tenant isolation

The current design uses one database per tenant. `RESOLVEOPS_TENANT_DATABASE_URLS_JSON` maps a
tenant ID to its database URL. The mapping is consulted only after authentication, using the tenant
ID stored with the credential. Request headers and resource IDs never choose a database.

This boundary covers all data in that database, including customers, employees, identities, team
memberships, repository access, cases, knowledge documents, embedding records, workflow state,
approvals, operation audits, tickets, notifications, and inbound events. An unknown or unconfigured
tenant fails closed with no fallback database and creates a security audit event. Because isolation
is physical, Packet 13 intentionally adds no `tenant_id` column migration to the domain tables.

Each tenant database must be migrated and seeded independently. A deployment should give every
tenant database a different least-privilege database account and should not grant cross-database
access to application accounts. ResolveOps rejects reused session factories and obvious duplicate
database targets during configuration so accidental sharing fails closed.

## Authentication and roles

API keys are opaque random values of at least 32 characters. Configuration stores only their
lowercase SHA-256 digests, never the original key. Comparison is constant-time, disabled identities
are rejected, duplicate digests are invalid configuration, and client errors do not reveal whether
an identity exists. Authentication success, failure, and missing or malformed credentials are
audited without recording presented credentials.

The roles are:

| Role | Read operations | Read PII | Issue refund | Grant repository access | Send notification | Create ticket |
| --- | --- | --- | --- | --- | --- | --- |
| Agent | Yes | No | No | No | Yes | Yes |
| Operator | Yes | Yes | Yes, up to deterministic limit | Yes | Yes | Yes |
| Approver | Yes | Yes | Yes, up to deterministic limit | Yes | Yes | Yes |
| System | Yes | Yes | Yes, up to deterministic limit | Yes | Yes | Yes |

Agents receive masked customer and employee names and email addresses, redacted notification
recipients, and redacted enterprise and Git usernames. Operator, approver, and system identities can
read full PII. This is data minimization, not a claim of field-level encryption. Existing
deterministic refund limits, approval checks, access eligibility, idempotency, state validation, and
post-action verification remain in force after RBAC.

The local MCP interface remains read-only and uses the least-privileged Agent role. It exposes no
write tools.

## Webhooks

Multi-tenant deployments configure `RESOLVEOPS_WEBHOOK_SECRETS_JSON`, with a unique secret of at
least 32 characters for every tenant. Duplicate secrets are rejected. A producer must send
`X-ResolveOps-Tenant`; ResolveOps selects both the verifier and database for that tenant. A valid
signature for tenant A cannot authenticate a request for tenant B.

The HMAC signs `<timestamp>.<raw-body>`. Existing replay-window, event-id idempotency, event ordering,
and state-transition checks still apply. See `docs/INTERFACES.md` for the full wire contract.

## Knowledge and model safety

Policy files are untrusted input. Before chunking, embedding, or storage, ingestion rejects hidden
HTML comments, unsafe invisible Unicode controls, executable payload markers, prompt-override
language, tool-execution requests, and common credential-exfiltration instructions. Rejection is
atomic: no document or embedding record is stored.

Pattern filtering is only defense in depth and cannot identify every possible malicious sentence.
The stronger boundary remains structural: retrieved policy and evidence are labelled untrusted in
the model instructions, model output must match a typed schema and known citations, and a model can
only recommend. It cannot select a tenant, grant permission, set a refund amount, call an action,
approve work, or mark an action verified.

The versioned offline adversarial dataset contains 17 attack and benign-control cases across
complaint intake and policy ingestion. All 17 pass at the recorded revision. CI runs the same gate
from `scripts/run_security_evaluation.py`; its stored report includes the dataset fingerprint and
explicitly does not claim coverage of novel semantic attacks.

## Secret handling and rotation

Database URLs, API-key identity JSON, and webhook secrets use masked secret settings. `.env` is
ignored by Git and `.env.example` contains placeholders only. Do not place plaintext production
keys, database passwords, or provider tokens in source, policy files, logs, exception messages, or
test fixtures committed to the repository.

`RESOLVEOPS_ENVIRONMENT` separates `development`, `demo`, and `production`. Development permits the
documented local defaults. Demo and production fail during application startup when they detect a
SQLite/local/example database, `TENANT-LOCAL`, placeholder webhook secrets, or malformed tenant
database configuration. Demo must enable signed demo sessions and route only to its synthetic
tenant. Production rejects demo mode and requires at least one enabled, non-example API identity.
These checks prevent an example file from silently becoming a deployable configuration; they do not
replace a secret manager or deployment review.

For production, inject values from the deployment platform's secret manager. To rotate an API key,
add a new digest, deploy it, move clients to the new key, then disable and remove the old identity.
To rotate a webhook secret without interruption, deploy a planned dual-key verifier before changing
the producer; the current single-key-per-tenant registry intentionally fails closed and does not
provide a hidden grace key.

## Repository and supply-chain checks

`scripts/security_check.py` inspects exactly the tracked and non-ignored files Git would publish. It
rejects a tracked `.env`, private-key file types, private-key blocks, and known token shapes for AWS,
GitHub, Google, OpenAI, and Slack without printing matching values. This focused check complements,
but does not replace, GitHub secret scanning or secret rotation after accidental disclosure.

The required CI security job also runs Bandit at medium-or-higher severity and `pip-audit` against
the installed dependency graph. GitHub Actions are pinned to full reviewed commit SHAs rather than
floating major-version tags. Dependabot is configured for Python, GitHub Actions, Docker, and
Terraform updates; automated update pull requests still require normal test and human review.

The latest local review found no credential patterns in publishable files, no medium/high Bandit
findings, and no known installed-package vulnerabilities. Test credentials, example database URLs,
example secret ARNs, and dataset fingerprints were reviewed as non-production fixtures. A clean scan
is evidence for the reviewed revision, not proof that every possible secret or vulnerability is absent.

## Traffic protection

Every HTTP request is checked before route processing. The service rejects a declared or streamed
body above `RESOLVEOPS_MAX_REQUEST_BODY_BYTES` (1 MiB by default) with HTTP 413. A bounded,
thread-safe token bucket separately charges a privacy-safe digest of the network identity and any
presented bearer credential. This prevents credential rotation from bypassing the network limit and
prevents multiple callers behind one address from bypassing their credential limit. Rejected bursts
receive HTTP 429 with `Retry-After` and rate-limit metadata. API keys are hashed before they become
in-memory bucket identifiers and never appear in responses or metrics.

The default is 120 requests per 60 seconds. Without Redis, the bounded fallback keeps at most 10,000
in-memory buckets with a 15-minute idle lifetime. With `RESOLVEOPS_REDIS_URL`, one Lua operation
atomically checks and consumes every privacy-safe identity key in the shared token bucket.
`/health`, `/health/live`, and `/health/ready` are exempt so orchestrator probes remain reliable;
the request-size limit still applies. A Redis outage uses the local limiter to preserve availability,
so a scaled deployment must alert on that fallback or enforce an equivalent gateway limit.

Do not trust arbitrary forwarded-client headers. The container no longer enables Uvicorn's wildcard
proxy trust. A deployment behind a reverse proxy must configure only that proxy's exact trusted
addresses before using forwarded identity for network rate limits.

## Current limitations

- API keys are suitable for the current service boundary, but no external identity provider,
  short-lived tokens, revocation service, or user lifecycle is included.
- Security audit events currently go to the configured application log sink unless a durable sink is
  supplied. Production should export them to append-only centralized storage with access controls.
- PII masking covers the current customer, employee, identity, Git-account, and notification read
  models. New PII-bearing models must add an explicit redaction policy and adversarial test before
  exposure.
- TLS, network segmentation, database encryption, backups, web-application firewall rules and cloud
  secret-manager policy remain deployment responsibilities. Shared quotas require configured Redis
  or an equivalent trusted gateway; the local fallback is intentionally limited.
- The ingestion guard reduces known prompt-injection forms; it does not make arbitrary external
  content trustworthy.
