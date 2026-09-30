# ResolveOps continuation point

Last verified: 2026-09-29

## Current state

- Branch: `codex-build`; all 17 planned implementation packets are committed and pushed.
- Final local suite before the documentation-only packet: 243 passed, 5 environment-dependent
  skips. Ruff, strict MyPy, medium/high Bandit, Compose config, and Terraform validation pass.
- Real Chromium covers complaint intake, refund approval, verified execution, reliability, IT
  approval/access, MFA safety stop, and demo reset.
- PostgreSQL concurrency covers duplicate money movement, approvals, webhooks and queue claims.
- Migration head is `0018_agent_workflow_jobs`; the current-head logical backup/restore drill passed
  and verified business records plus all agent durability tables.
- The Docker/Compose implementation includes PostgreSQL, API, migrations, demo seed, Redis and a
  worker. Validated AWS Terraform includes private ECS API/worker, RDS, TLS Valkey, ALB, ECR,
  Secrets Manager and CloudWatch.
- No public cloud resources were created.

## Current evidence

- Customer workflow: 24/24; Employee/IT: 14/14; multi-agent trajectories: 22/22.
- Response automated safety/grounding: 24/24; human review: **0/24 pending**.
- Adversarial complaint/policy inputs: 17/17.
- Seven versioned manifests contain 154 records.
- Hybrid retrieval: 0.9800 Recall@3, 0.9233 MRR, 0.9363 nDCG@3. The reranker improved ranking
  slightly but failed the 250 ms p95 rule and was not adopted.
- Pgvector exact search at 10,000 synthetic vectors: 8.02 ms p95 versus 363.24 ms Python exact;
  online search remains in process for the real 17-chunk corpus.
- Scale: 151,862 records. Mixed API: 232/232 requests including 30 writes. Durable queue: 200/200
  claims exactly once across eight workers.
- Offline trajectory usage: 182 model-double calls and 71,991 estimated input tokens over 22 cases.
  Live multi-agent provider cost is unknown.

## Boundaries to preserve

- Agents recommend; deterministic software authenticates, authorizes, approves, executes, audits,
  and verifies.
- Never expose or commit `.env`, provider keys, credentials, prompts, raw model output, or real PII.
- Do not claim public deployment, human review, production SLOs, production scale, or live vendor
  integration without direct evidence.
- PostgreSQL is durable job truth. Redis/Valkey is coordination only.
- Reviewed memory is tenant scoped, policy-version matched, expiring and advisory.
- Do not add Kubernetes, Kafka, another agent framework, more agents, GraphRAG, fine-tuning, another
  vector database or microservices without measured need.

## Owner-dependent next steps

1. Revoke and replace the Gemini key that was pasted into chat; save the replacement only in the
   ignored local `.env` or a cloud secret manager.
2. Review the 24 responses using `evals/responses/README.md`; only the owner can provide honest human
   labels.
3. Decide whether to make the GitHub repository public after a final history/credential review.
4. Optionally record `docs/DEMO_SCRIPT.md` after checking the video for secrets and notifications.
5. Optionally authorize an AWS account and budget. The checked-in architecture can incur charges.

## Resume instruction

Tell Codex: `Continue ResolveOps from docs/CONTINUATION.md and verify the current branch before any external change.`
