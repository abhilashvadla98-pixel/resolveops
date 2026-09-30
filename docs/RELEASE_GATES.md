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
- Reviewed operator feedback can become a versioned dataset candidate only after human review.
- README, project rules, license and the technical walkthrough script are release-oriented.

## Owner gates before a final v1 release

1. Rotate the Gemini key that appeared outside local secret storage. Do not reuse it.
2. Put the new key only in ignored local `.env` storage and set
   `RESOLVEOPS_GEMINI_KEY_ROTATED=true`.
3. Run the 30-trial live multi-agent evaluation and retain its honest report.
4. Manually label all 24 response-review rows. Code must not create these labels.
5. Submit and review one genuine operator correction, promote it to a versioned dataset, make the
   resulting change, and add/pass the focused regression test. Do not invent this example.
6. Record the 60–90 second technical walkthrough using a verified live trace.
7. Deploy the synthetic public demo only through an owner-approved free host/account. Keep AWS
   Terraform labelled reference infrastructure unless AWS is actually deployed.
8. Create the final v1 GitHub release and pin the repository only after the gates above are true.

Until then, an RC is honest; a final production-ready claim is not.
