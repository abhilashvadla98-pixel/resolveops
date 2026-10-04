# Workflow evaluation datasets

`customer_operations.jsonl` version 2 contains 24 engineering-authored product cases that run through the real
ResolveOps workflow, policy retrieval, database stores, authorization rules, action tools, and
final-state verification. Each case starts from an isolated database so one result cannot leak into
another.

The dataset covers:

- verified duplicate-charge and return-refund submissions that remain open while settlement is pending
- ambiguous, pending, incomplete, and already-refunded cases
- permission and approval-limit failures
- missing required policy
- grounded reasoning, manual-review advice, invalid citations, and provider failure
- provider timeouts, false success, and delayed verification

Dataset SHA-256:
`292a14c3cef172b16b3cfdfe31fe7baec31c2d6917d514260ec7125ba770763b`.

Version 2 replaces obsolete tests requiring a preconfirmed fixture or caller-supplied proposal with
explicit missing/conflicting obligation evidence and an unlinked return. It checks workflow status,
persisted issue status, and linked refund status. `verified` means the submission was independently
read, not that money settled. These are deterministic regression labels, not owner response-review labels.

## Reproduce

```powershell
.\.venv\Scripts\python.exe -m resolveops.evaluation.run
```

To save the detailed machine-readable report:

```powershell
.\.venv\Scripts\python.exe -m resolveops.evaluation.run --output artifacts/customer-regression.json
```

The command exits with status 1 if any case fails, making it suitable as a regression gate.

## Measured result — version 2

Measured locally on 2026-10-04 with deterministic feature-hash embeddings and scripted reasoning
where configured. No live model or external payment-provider calls were made. The report is
[`settlement-v2-report.json`](settlement-v2-report.json); the older `latest-report.json` is historical
version-1 evidence and does not validate the current contracts.

| Category | Cases | Passed |
| --- | ---: | ---: |
| Successful submission (settlement pending) | 3 | 3 |
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
