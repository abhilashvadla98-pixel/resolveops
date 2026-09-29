# Lightweight experiment artifacts

ResolveOps stores experiments as reviewable JSON files rather than introducing an experiment
platform. An artifact identifies the Git revision, versioned dataset, provider/model, prompt and
schema versions, embedding and retrieval configuration, policy/index version, measured metrics,
latency, token usage, reported cost, and failure-taxonomy counts.

Only provider-reported token or cost values should be recorded. Unknown values remain absent.

```text
python scripts/run_experiment.py record --manifest ... --metrics ... --output ...
python scripts/run_experiment.py compare experiments/results/run-a.json experiments/results/run-b.json
```
