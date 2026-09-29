# Customer Operations retrieval evaluation

`customer_operations.jsonl` is a hand-authored retrieval set covering duplicate payments, payment
states, return refunds, return eligibility, customer communication, and escalation. Some questions
require more than one policy. Relevance is labeled at the policy-document level; retrieved chunks
are deduplicated by document before metrics are calculated.

## Reproduce

Run migrations, then execute:

```powershell
.\.venv\Scripts\python.exe -m resolveops.knowledge.evaluate --provider fastembed --k 3
```

The evaluation command ingests any missing documents and embeddings before running vector, BM25,
and hybrid retrieval against the same active, effective policy corpus.

## Measured baseline

Measured on 2026-09-24 with Python 3.12, FastEmbed 0.8.1,
`BAAI/bge-small-en-v1.5`, 6 policy documents, 17 chunks, and 15 queries at K=3.
Dataset SHA-256:
`8d8ccfce9281a52cfc00b0fe20e4f78006dc694345ba59e3fd40ac0301af3533`.

| Method | Recall@3 | MRR | nDCG@3 |
| --- | ---: | ---: | ---: |
| Vector | 0.9333 | 0.8667 | 0.8841 |
| BM25 | 1.0000 | 0.8889 | 0.9121 |
| Hybrid RRF | 1.0000 | 0.9222 | 0.9421 |

These numbers describe only this small checked-in dataset. They are regression evidence, not a
claim of general production accuracy. Hybrid retrieval improved ranking quality over the vector
baseline. A cross-encoder reranker was not added because this corpus and result set do not yet
justify its extra model, latency, and operational complexity.
