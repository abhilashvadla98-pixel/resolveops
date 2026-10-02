# Public release gates

## Completed in code

- Complex customer investigations route through the five-role graph inside the normal workflow.
- The separate operator-facing multi-agent button is removed.
- Four reusable typed Agent Skills declare context, tools, budgets and eval coverage.
- Context tests cover tenant denial, token/character bounds, stale evidence and injected text.
- The 22-case offline trajectory regression and 8-case reviewed-memory ablation are reproducible.
- The read-only MCP server and one real `get_case` consumer path are tested, including fail-closed
  denial and availability-only fallback.
- The 10-task × 3-trial live runner records routing, tools, citations, critic behavior, latency,
  tokens, calls and cost when known.
- Human response-review export/import requires explicit owner labels.
- Reviewed operator feedback can become a versioned dataset candidate only after human review. One
  real example is retained in `evals/feedback/owner-corrections-v1.jsonl` with a hashed manifest and
  focused browser regression.
- README, project rules, license and the technical walkthrough script are release-oriented.

## Public v1 status

The public synthetic demo, `v1.1.0` GitHub release, teaser and technical walkthrough videos,
default `main` branch, CI badge, repository metadata, license, and profile pin are complete. Render
deployment evidence is recorded in `docs/PUBLIC_DEMO.md`; AWS Terraform remains reference
infrastructure. The replacement Gemini credential stays only in ignored local storage. The
30-trial report and a separate verified provider-backed trace are checked in with their limitations.

## Open evidence gates

One evidence gate remains open: the owner must manually label all 24 response-review rows. Code
must not create these labels. Until that review is complete, ResolveOps is a released,
production-minded reference implementation with a public synthetic demo—not a production
deployment or a validated business system.
