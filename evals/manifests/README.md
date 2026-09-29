# Versioned evaluation datasets

Each JSON manifest gives an evaluation dataset a stable identity and semantic version. It records
why the dataset exists, how it was created, its labels and categories, exact record count, and a
SHA-256 fingerprint. A dataset content change requires a new version and fingerprint.

Validate the complete catalog through `load_manifest_catalog` or the corresponding tests before
running experiments. Experiment artifacts reference both the semantic version and fingerprint so
results cannot silently move to a different benchmark.
