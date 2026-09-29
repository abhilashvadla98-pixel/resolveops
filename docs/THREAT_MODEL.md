# ResolveOps threat model

Last reviewed: 2026-09-27

## Assets and trust boundaries

Protected assets include customer PII, payment and refund state, case evidence, policy knowledge,
workflow and approval state, action idempotency records, audit history, API credentials, webhook
secrets, and database credentials.

The important boundaries are:

1. An API caller crosses the HTTP authentication boundary.
2. An authenticated principal crosses the tenant-router boundary into exactly one database.
3. Internal actors cross RBAC and deterministic action-control boundaries.
4. A payment provider crosses the per-tenant HMAC webhook boundary.
5. Policy authors and imported documents cross the untrusted-knowledge boundary.
6. Optional model output crosses a typed, advisory-only reasoning boundary.
7. Operators and the deployment platform cross the secret and infrastructure boundary.

## Threats, controls, and remaining risk

| Threat | Implemented controls | Remaining risk / required operations |
| --- | --- | --- |
| Missing, guessed, or stolen API key | Bearer authentication; minimum key length; only SHA-256 digests configured; constant-time comparison; generic failures; audit events; network and credential rate limits | Use high-entropy keys, TLS, centralized audit alerts, rotation, and short-lived identity when available |
| Caller claims another tenant | Tenant comes only from authenticated identity; database-per-tenant registry; no default fallback; adversarial header test | Protect identity configuration and database credentials; prevent infrastructure-level cross-database grants |
| Cross-tenant identifier lookup | Every simulator session is created from the authenticated tenant database | New interfaces must use the same dependency; automated architecture checks could strengthen this later |
| Excessive PII disclosure | Explicit `read_pii` permission; Agent masking; tests for customer and notification views | Expand field inventory and redaction whenever new PII is modeled; control logs and exports |
| Privilege escalation or unsafe money movement | Server-created Actor; fixed role-permission map; refund limits; human approval; deterministic policy/state gates; idempotency; fresh verification | Identity administration and separation-of-duty policy remain deployment responsibilities |
| Cross-tenant forged webhook | Tenant-specific unique HMAC secrets; tenant header selects matching verifier and database; replay window; event idempotency and ordering | Rotate secrets, protect producer systems, use TLS, and monitor repeated failures |
| Replay or out-of-order provider event | Timestamp window; event-ID conflict handling; per-refund cursor; allowed transitions | Clock health and provider retry policy must be monitored |
| Malicious policy prompt injection | Pre-storage content guard; untrusted-data model instruction; typed output; known-citation validation; advisory-only model role | Semantic and obfuscated attacks remain possible; review provenance and restrict who can publish policy |
| Model fabricates evidence or requests a tool | Citation allowlist; structured validation; deterministic workflow and action gates; no tool access in reasoning provider | Model quality is not guaranteed; uncertain results must remain in review |
| Secret leaked through settings or audit | Secret-valued configuration; no plaintext API keys at rest; audit schema excludes credentials; repository ignores `.env` | Application logs, crash dumps, CI output, and cloud configuration still require operational controls |
| Malicious or compromised MCP client | Read-only tool registration; Agent role; no action or approval tools | Add authenticated transport and tenant-aware deployment before remote MCP exposure |
| Denial of service | Global request-size gate; bounded network-and-credential token buckets; bounded bucket storage; health-probe exemption; workflow/retry limits | The limiter is process-local; add shared gateway/distributed quotas, connection limits, a WAF, and autoscaling for a scaled deployment |
| Database or host compromise | Tenant databases reduce blast radius | Encryption, patching, network policy, backups, incident response, and managed key controls are external |

## Abuse cases verified in tests

The adversarial suite checks unauthenticated and invalid API requests, an untrusted tenant header,
an identity pointing to an unavailable tenant, masked versus full PII by role, isolation of knowledge
records, workflow records, tickets, and operation results, secret-safe settings and authentication
audit data, six malicious policy payload classes, benign policy acceptance, and a tenant A webhook
signature attempted against tenant B.

## Security review rule

Any new public route, MCP tool, PII field, write action, tenant-scoped store, knowledge source, model
capability, or external event type must update this threat model and add a test proving that the
relevant boundary fails closed.
