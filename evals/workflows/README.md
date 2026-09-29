# Workflow evaluation datasets

`customer_operations.jsonl` contains 24 hand-authored product cases that run through the real
ResolveOps workflow, policy retrieval, database stores, authorization rules, action tools, and
final-state verification. Each case starts from an isolated database so one result cannot leak into
another.

The dataset covers:

- successful duplicate-charge and return-refund resolutions
- ambiguous, pending, incomplete, and already-refunded cases
- permission and approval-limit failures
- missing required policy
- grounded reasoning, manual-review advice, invalid citations, and provider failure
- provider timeouts, false success, and delayed verification

Dataset SHA-256:
`707249aa5afc5fd88b321c78ddea8891a54919ad7e8ad577c8c0d969fcc354e5`.

## Reproduce

```powershell
.\.venv\Scripts\python.exe -m resolveops.evaluation.run
```

To save the detailed machine-readable report:

```powershell
.\.venv\Scripts\python.exe -m resolveops.evaluation.run --output evals/workflows/latest-report.json
```

The command exits with status 1 if any case fails, making it suitable as a regression gate.

## Measured result

Measured locally on 2026-09-27 with Python 3.12 and deterministic feature-hash embeddings:

| Category | Cases | Passed |
| --- | ---: | ---: |
| Successful resolution | 3 | 3 |
| Ambiguous / incomplete | 6 | 6 |
| Already refunded | 2 | 2 |
| Permission / approval | 4 | 4 |
| Policy failure | 2 | 2 |
| Reasoning behavior | 4 | 4 |
| Tool failure / recovery | 3 | 3 |
| **Total** | **24** | **24** |

This is exact agreement with the checked-in expected outcomes, not a claim of production accuracy.
The dataset is intentionally small enough to review and will need broader human-labeled cases as
the product and second domain pack grow.

## Employee and IT access

`employee_it.jsonl` contains 14 hand-authored cases that run the real Employee/IT workflow, policy
retrieval, authorization, action transaction, audit, and fresh verification. It covers success,
advisory reasoning, role denial, employment and identity eligibility, MFA, team membership, Git
account state, manager approval, partial-state conflict, existing-access idempotency, and missing
policy.

Dataset SHA-256:
`3144d8f60bb1489dd5fe371ef24c7257ecab1a783f2311b1286080caadce3211`.

Run and save the report with:

```powershell
.\.venv\Scripts\python.exe -m resolveops.evaluation.run_employee `
  --output evals/workflows/employee-it-latest-report.json
```

Measured locally on 2026-09-27 with Python 3.12 and deterministic feature-hash embeddings:

| Category | Cases | Passed |
| --- | ---: | ---: |
| Success | 1 | 1 |
| Eligibility | 5 | 5 |
| Approval | 2 | 2 |
| Permission | 1 | 1 |
| Idempotency and conflict | 2 | 2 |
| Policy | 1 | 1 |
| Reasoning | 2 | 2 |
| **Total** | **14** | **14** |
