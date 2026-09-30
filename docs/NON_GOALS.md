# Non-goals and rejected complexity

ResolveOps is a single operations application with two domain packs and a small policy corpus. The
following are deliberate non-goals until measurements show a need.

- **Kubernetes:** one application container and PostgreSQL do not justify a cluster control plane.
- **Kafka:** the current webhook and workflow volume does not require a distributed event log.
- **Microservices:** splitting workflows, actions, and policy retrieval would add network failure
  modes and distributed transactions without an independent scaling requirement.
- **GraphRAG:** policies have explicit metadata, headings, and few cross-document relationships;
  hybrid lexical/vector retrieval is easier to inspect.
- **A separate vector database:** exact search over the current corpus is measurable and fast.
- **Cross-encoder reranking in production:** the experiment improved MRR and nDCG slightly but
  raised local p95 from about 46 ms to about 1,180 ms, violating the adoption rule. Reconsider after
  corpus growth or a materially faster serving path.
- **Fine-tuning:** structured prompts, policy evidence, and deterministic gates address the current
  task without training data or model hosting.
- **Additional agents beyond five justified roles:** Supervisor, Investigation, Policy, Resolution,
  and independent Critic cover the current reasoning boundaries. More roles would add calls and
  coordination without a measured gap.
- **A React/Vue frontend:** the current console is small enough that a second toolchain and service
  would add operational work without improving the workflow.
- **LLM-as-judge for deterministic facts:** refund persistence, IDs, policy citations, approval
  status, and verification are checked directly. Human review is reserved for response clarity and
  tone.
- **Automatic financial compensation:** reversing refunds or messages can create additional harm;
  unclear recovery remains a visible manual-review task.

These choices are not universal recommendations. They are the smallest design that satisfies the
current evidence, safety boundaries, and expected operating scale.
