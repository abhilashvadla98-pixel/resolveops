# Customer Operations retrieval evaluation

`customer_operations.jsonl` is a 50-question, hand-authored retrieval set covering duplicate
payments, payment states, return refunds, return eligibility, customer communication, and
escalation. It labels direct lookups, hard negatives, similar policies, wrong-issue terminology,
multi-section answers, and confusing terminology. Some questions require more than one policy.
Relevance is labeled at the policy-document level; retrieved chunks are deduplicated by document
before metrics are calculated.

## Reproduce

Run migrations, then execute:

```powershell
.\.venv\Scripts\python.exe -m resolveops.knowledge.evaluate --provider fastembed --k 3
```

The evaluation command ingests any missing documents and embeddings before running vector, BM25,
and hybrid retrieval against the same active, effective policy corpus.

## Measured baseline

Measured on 2026-09-29 with Python 3.12, FastEmbed 0.8.1,
`BAAI/bge-small-en-v1.5`, 6 policy documents, 17 chunks, and 50 queries at K=3.
Dataset SHA-256:
`9274c72f275e1369e931a225a5023ba0afbd32e16a4822a3947bd0e3b33e5242`.

| Method | Recall@3 | MRR | nDCG@3 |
| --- | ---: | ---: | ---: |
| Vector | 0.9200 | 0.9100 | 0.9024 |
| BM25 | 0.9800 | 0.9467 | 0.9418 |
| Hybrid RRF | 0.9800 | 0.9233 | 0.9363 |

Hybrid category results expose the weaker slices instead of reporting only one average:

| Category | Queries | Recall@3 | MRR | nDCG@3 |
| --- | ---: | ---: | ---: | ---: |
| Confusing terminology | 5 | 1.0000 | 1.0000 | 1.0000 |
| Direct lookup | 14 | 1.0000 | 0.9167 | 0.9379 |
| Hard negative | 16 | 0.9375 | 0.8750 | 0.8914 |
| Multi-section | 7 | 1.0000 | 1.0000 | 1.0000 |
| Similar policy | 4 | 1.0000 | 1.0000 | 0.9799 |
| Wrong issue type | 4 | 1.0000 | 0.8333 | 0.8750 |

These numbers describe only this checked-in policy set. They are regression evidence, not a claim
of general production accuracy. Hybrid beat the vector baseline but did **not** beat BM25 on MRR or
nDCG in this run. Hard negatives and wrong-issue terminology remain the weakest hybrid slices. A
cross-encoder reranker was not added because six documents still do not justify its model, latency,
and operational complexity; improving query labels and fusion weights is the cheaper next step.

The active corpus has no superseded policy version and no meaningful "no relevant policy" answer,
so those two categories are not padded with invented examples. Effective-date exclusion is covered
by focused knowledge tests. Add those retrieval categories when the policy corpus contains honest
ground truth for them.
