# Customer-response evaluation

## Human review workflow

The checked-in truth remains **0/24 human reviewed**. Export an unlabeled review sheet with:

```text
python scripts/export_response_review.py
```

The owner fills `yes` or `no` for factual accuracy, groundedness, correct outcome, absence of an
unsupported promise, clarity, and tone; then selects `approved` or `needs_revision`, identifies
the reviewer, and writes a note. Importing validates completeness and writes a separate candidate
file under `review-work/`; it never changes the versioned dataset or promotes feedback
automatically.

This set contains 24 grounded response candidates covering verified refund creation, an already
existing refund that is still pending externally, and cases that must stop for review. The automated
checks require verified identifiers and policy references, require outcome-specific language, and
reject unsupported completion or action claims.

Run it with:

```text
python scripts/run_response_evaluation.py
```

The generated `latest-report.json` includes every candidate message and assertion. It deliberately
reports `0/24 human reviewed` until a person completes the rubric below. Automated checks are useful
safety evidence, but they are not a substitute for human judgment about clarity and tone.

## Human review rubric

For each JSONL case, read the generated candidate and check all five questions:

1. Is the outcome factually consistent with the scenario?
2. Does it avoid claiming that an external provider finished settlement?
3. Does it clearly say whether ResolveOps created a record, avoided a duplicate, or stopped?
4. Is the language understandable and respectful to a customer?
5. Does it give an honest next state: provider processing, pending status, or manual review?

Only after a real reviewer answers all five should they change `human_review_status` to `approved`
or `needs_revision` and add both `reviewer` and `review_note`. Re-run the command to update the
human-review totals. Do not bulk-mark the set as reviewed without reading the candidates.
