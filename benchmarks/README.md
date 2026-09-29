# Measured benchmarks

`scale/` documents the isolated PostgreSQL scale method. `results/` contains only completed,
measured artifacts. Profiles and scripts are capabilities, not claims.

The scale runner deliberately refuses any database whose name does not contain `benchmark`, then
recreates only that isolated database schema between sizes. The API runner is read-only and
bounded by default; sensitive mutation traffic requires a separate resettable environment and is
not silently mixed into a shared demo.

Measured artifacts currently include:

- `scale-before-case-index-2026-09-29.json` — three PostgreSQL sizes before the queue index;
- `scale-after-case-index-2026-09-29.json` — the same sizes after the evidence-driven index;
- `load-saturation-unpaced-2026-09-29.json` — an unpaced run that exceeded rate protection; and
- `load-soak-paced-2026-09-29.json` — 90/90 successful requests at a bounded 1.5 target RPS.

The first load artifact predates per-status reporting, so its errors are not retroactively assigned
invented status codes. The measured behavior and follow-up are documented in `docs/PERFORMANCE.md`.
