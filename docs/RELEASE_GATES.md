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

The public synthetic demo, `v1.0.1` GitHub release, teaser video, default `main` branch, CI badge,
repository metadata, license, and profile pin are complete. Render deployment evidence is recorded
in `docs/PUBLIC_DEMO.md`; AWS Terraform remains reference infrastructure.

## Open evidence gates

These are limitations of v1, not silently treated as complete:

1. Rotate the Gemini key that appeared outside local secret storage. Do not reuse it.
2. Put the replacement only in ignored local `.env` storage and set
   `RESOLVEOPS_GEMINI_KEY_ROTATED=true`.
3. Run the 30-trial live multi-agent evaluation and retain its honest report.
4. Manually label all 24 response-review rows. Code must not create these labels.
5. Record the 60–90 second technical walkthrough using a verified live provider trace.

Until those gates close, ResolveOps is a released, production-minded reference implementation with
a public synthetic demo—not a production deployment or a validated business system.
