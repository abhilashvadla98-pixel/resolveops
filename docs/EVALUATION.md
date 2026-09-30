# ResolveOps evaluation

ResolveOps evaluates retrieval and end-to-end workflow behavior separately. This prevents a good
final answer from hiding bad retrieval, and prevents a retrieval score from being mistaken for safe
case resolution.

Every evaluation set has a manifest under `evals/manifests/` with a stable dataset ID, semantic
version, exact record count, SHA-256 hash, task type, split, creation method, and review status. The
six manifests currently cover 137 records. Tests verify every hash so a changed dataset cannot be
mistaken for the previous baseline.

## Multi-agent trajectory contracts

`python scripts/run_agent_evaluation.py` runs 22 hand-authored synthetic scenarios through the real
hierarchical orchestrator with a deterministic offline provider double. Together with the 24
customer and 14 employee-IT workflow cases, the repository contains 60 versioned operational
workflow/trajectory cases. The agent suite checks all five roles, bounded read tools, critic
decisions, replanning, escalation, forbidden writes, call budgets, and both domains. It makes no
paid model calls and does not claim live-model quality or human labels. The stored report includes
the dataset checksum, environment, measured local latency, estimated context tokens, and explicit
limitations.

## Retrieval evaluation

The retrieval benchmark contains 50 hand-authored questions over six versioned policy documents.
It measures Recall@K, MRR, and nDCG independently for vector, BM25, and hybrid retrieval, including
category-level results for direct lookups, hard negatives, similar policies, wrong-issue terms,
multi-section answers, and confusing terminology. Its dataset, measured baseline, and reproduction
command are in `evals/retrieval/README.md`.

## Workflow regression evaluation

The workflow benchmark contains 24 Customer Operations cases. Every case creates an isolated local
database, loads the real seed data and policies, applies one declared scenario fixture, and executes
the real `CustomerIssueWorkflow`. It does not replace workflow code with a mocked decision.

Each expected result checks:

- terminal outcome and decision
- exact error code where review is required
- whether a new refund was actually persisted
- whether final-state verification succeeded
- required and forbidden workflow nodes
- presence of the controlling policy citation
- evidence and policy-reference grounding when scripted reasoning is used

The runner records every assertion and continues after a broken case so one crash does not hide
later failures. It exits unsuccessfully when any case fails. The detailed report is JSON and can be
saved for CI artifacts.

Run the gate with:

```powershell
.\.venv\Scripts\python.exe -m resolveops.evaluation.run
```

The checked-in measured result is 24 of 24 cases passing. Category counts and the dataset checksum
are recorded in `evals/workflows/README.md`; detailed observations are in
`evals/workflows/latest-report.json`. These numbers are reproducible regression evidence only, not
an estimate of general accuracy, business savings, or production readiness.

## Employee and IT workflow regression

Packet 15 adds a separate 14-case dataset for `EmployeeAccessWorkflow`. It covers the successful ML
Platform access grant, supported and non-supportive advisory reasoning, role denial, employment and
identity eligibility, MFA, team membership, Git account state, manager approval, partial-state
conflicts, existing-access idempotency, and missing active policy. Every case gets an isolated
database and runs the real workflow, action controls, persistence, and policy retrieval.

Run it with:

```powershell
.\.venv\Scripts\python.exe -m resolveops.evaluation.run_employee
```

The checked-in result is 14 of 14 cases passing. The full observations are in
`evals/workflows/employee-it-latest-report.json`. These designed regression cases are not a claim of
statistical coverage or external vendor performance.

## Semantic evaluation decision

No LLM-as-judge is used in the required regression gate. Current ground truth—authorization,
workflow state, refund persistence, error codes, policy IDs, evidence IDs, and final verification—is
directly testable and is more reliable when scored deterministically.

Reasoning cases still test semantic-system boundaries that matter: supported recommendations,
manual-review recommendations, provider failure, unknown evidence references, and unknown policy
citations. Valid reasoning must point to evidence and policy chunks actually supplied to it. Natural
language style is not scored because there is no calibrated human-labeled rubric yet. An LLM judge
should be added only for a genuinely subjective requirement and calibrated against human labels.

Response candidates can be exported with `scripts/export_response_review.py`. The owner rubric asks
for factual accuracy, groundedness, correct outcome, absence of unsupported promises, clarity, and
tone. `scripts/import_response_review.py` requires an explicit reviewer, decision, note, and yes/no
answer for every rubric field. It writes a separate candidate artifact and never changes the
versioned dataset automatically. Current human-review truth remains **0/24**.

## Reproducible experiment records

`scripts/run_experiment.py` records or compares lightweight JSON artifacts. Each artifact binds the
result to the current Git revision, dataset identity/version/hash, provider and model, prompt and
schema versions, embedding and retrieval settings, policy/index version, task metrics, latency,
provider-reported tokens/cost, failure counts, and timestamp. Unknown usage or cost remains absent;
it is never estimated and presented as provider data.

## Optional live reasoning evaluation

`evals/reasoning/live_reasoning.jsonl` contains three synthetic reasoning cases: a confirmed
duplicate charge, an existing refund that must be monitored, and insufficient payment evidence that
must route to review. The live gate checks the expected conclusion, disposition, evidence citations,
and policy citations. It records the returned assessment, request latency, and provider-reported
token usage in a JSON artifact. It never gives the model an action tool or treats its recommendation
as authorization.

The live gate is deliberately separate from required CI because it uses external quota and can fail
when the provider is unavailable. Put the Gemini free-tier key in the ignored local `.env` file as
`RESOLVEOPS_GEMINI_API_KEY`, then run:

```powershell
.\.venv\Scripts\python.exe -m resolveops.evaluation.live_reasoning `
  --output evals/reasoning/gemini-live-report.json
```

The key must never be written to the repository or a report. Free-tier requests use synthetic data
only because Google states that free-tier content may be used to improve its products. A checked-in
report may be described only as the observed result for its recorded model, cases, and run time—not
as a general model-quality claim.

### Recorded live result

The gate ran successfully on 2026-09-28 with `gemini-3.5-flash-lite`. All 3 of 3 synthetic cases
passed the expected conclusion, disposition, evidence-citation, and policy-citation checks. The
provider reported 1,058 input tokens, 531 output tokens, and 1,589 total tokens. Observed latency
was 1.49-6.77 seconds per request with a 4.74-second median.
The machine-readable evidence is `evals/reasoning/gemini-live-report.json`. This result proves the
external-model integration path worked for this run only; it is not a production SLO or broad model
benchmark.

## Regression policy

The workflow dataset and expectations are version-controlled. A changed product rule should update
code, tests, dataset expectations, checksum, and documentation together. A lower score must never be
silently accepted by reducing an expectation. New production bugs should become focused regression
cases when they can be represented safely.

## Current limitations

- The workflow sets have 38 carefully reviewed cases in total, not the longer-term 300–500 case
  target.
- It varies a realistic flagship case topology; it is not a statistically representative customer
  distribution.
- The required regression gates use deterministic offline embeddings and a scripted reasoning
  provider. The optional live gate has only three synthetic cases and is not a statistically
  representative external-model benchmark.
- Employee/IT evaluation currently concentrates on the repository-onboarding flagship scenario.
