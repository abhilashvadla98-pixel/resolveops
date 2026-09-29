# ResolveOps continuation point

Last verified: 2026-09-29

## Current state

- Branch: `codex-build`.
- Final-pass commits are pushed to `origin/codex-build`; the latest GitHub CI run is the release
  gate for any public presentation.
- The complete local suite passes with 195 tests and 4 environment-dependent skips.
- Ruff formatting/linting and MyPy pass across 130 source files.
- The real Chromium test completes complaint intake, refund approval, verified execution, reliability
  inspection, and the Employee/IT access workflow.
- Real PostgreSQL concurrency tests passed for simultaneous refund execution, duplicate approval,
  and duplicate webhook delivery.
- PostgreSQL migration upgrade → downgrade → re-upgrade passed through migration 0011.
- The guarded PostgreSQL backup/restore drill passed and verified both scenario A and `CASE-1001`.
- The locked non-root Docker image built and ran as UID 10001.
- Existing local demo containers were not removed or modified by temporary verification containers.

## Current evidence

- Customer workflow evaluation: 24/24.
- Employee/IT workflow evaluation: 14/14.
- Customer response automated safety/grounding evaluation: 24/24.
- Customer response human review: **0/24; pending**.
- Retrieval: 50 hand-authored queries. FastEmbed vector 0.9200 Recall@3, 0.9100 MRR,
  0.9024 nDCG@3; BM25 0.9800/0.9467/0.9418; hybrid 0.9800/0.9233/0.9363.
- Offline performance artifact: 72 workflows, p50 19.29 ms and p95 34.92 ms. This is a local
  regression sample, not a production SLO.
- Optional recorded Gemini gate: 3/3 synthetic cases passed on 2026-09-28. Live model access is not
  required for the product or its tests.

## Important boundaries to preserve

- Model output is advisory. It cannot choose an actor, approve, execute, or verify an action.
- Identity, tenant, and role come from the authenticated server boundary, never a request body.
- Refund and access actions remain permission-checked, idempotent, audited, and freshly verified.
- Possible post-commit failures use verify-only recovery; do not blindly repeat a side effect.
- Demo sessions may access only synthetic data. Normal production mode cannot enable the demo.
- Simulator routes stay read-only. Mutations use authenticated operations endpoints and the same
  deterministic action layer as internal workflows.
- Do not claim external provider settlement, live vendor integrations, human review, a public cloud
  deployment, or production-scale performance without direct evidence.
- Do not expose `.env`, API keys, account pages, credentials, or real customer/employee data in a
  screenshot, commit, log, trace, metric, or response.

## What remains owner-dependent

1. Read and score the 24 response candidates using `evals/responses/README.md`; add a real reviewer
   and note for each reviewed item.
2. Decide whether the repository should become public. Before changing visibility, run the final
   credential/history review and confirm that the displayed GitHub profile is the intended account.
3. Record a short local demo video or approved synthetic screenshots if desired.
4. Choose whether to stay local/free or authorize a cloud provider and budget. No cloud resources
   are currently deployed. The checked-in AWS reference can incur charges.
5. Add the final public repository/demo link to the resume only after it exists and is verified.

## Resume instruction

Tell Codex: `Continue ResolveOps from docs/CONTINUATION.md and verify the current branch before any external change.`
