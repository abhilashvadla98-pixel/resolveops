# ResolveOps synthetic operational data

This directory contains the small, reviewable data contract for the project. Large generated
datasets are deliberately not committed.

## Reproducible workflow

```text
python scripts/generate_data.py --profile demo --output generated-data/demo
python scripts/validate_data.py generated-data/demo
python scripts/load_data.py generated-data/demo
```

Profiles are defaults, not benchmark claims. Every count can be overridden with
`--customer-cases`, `--it-requests`, `--seed`, and `--anomaly-rate`. The generated manifest
records the actual row counts, labels, seed, version, files, and checksums.

| Profile | Default customer cases | Default IT requests | Intended use |
|---|---:|---:|---|
| demo | 18 | 8 | Populated local operator console |
| small | 1,000 | 250 | Development and data-quality checks |
| medium | 10,000 | 2,500 | Practical PostgreSQL scale testing |
| large | 50,000 | 12,500 | Controlled higher-volume testing |

These sizes are configurable. A profile is not described as tested until its checked-in
benchmark artifact shows a completed run.

Generated records use reserved synthetic identifiers and `example.test` email addresses. They
must never be mixed with production data. Validation reports exact failures and refuses to load
an invalid dataset; it does not silently repair records.
