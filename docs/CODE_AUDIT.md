# Code audit

Audit date: 2026-09-29

This is an evidence-based maintainability review, not a claim that the code has no defects. The
review used the configured Ruff rules, MyPy, the complete test suite, Ruff's cyclomatic-complexity
and branch/statement checks, file-size inspection, and targeted searches for unused imports,
placeholder implementations, and unfinished markers.

## What changed during the audit

- Split workflow timeline projection out of `customer_issue.py` into `workflows/timeline.py`. The
  workflow file fell from 957 to about 850 lines, and timeline event construction is now a set of
  small, typed functions selected through a dispatcher instead of one long conditional method.
- Split non-development configuration validation into separate environment, database, tenant,
  webhook, and production-identity checks. `validate_runtime_safety` is no longer reported as a
  complex function, while its fail-closed behavior and tests remain unchanged.
- Extracted durable approval resumption from the main approval gate. The gate is no longer above the
  configured complexity threshold, and the new helper still validates the approval ID and requires
  a lifecycle store.

## Largest production modules

The largest modules after the changes are approximately:

| Module | Lines | Decision |
| --- | ---: | --- |
| `operations/actions.py` | 1,093 | Keep for now; it centralizes transaction, lease, retry, audit, and verification invariants. Split only with operation-contract tests around each extracted service. |
| `workflows/customer_issue.py` | ~850 | Improved in this pass; graph topology and node behavior remain together so the workflow is still readable end to end. |
| `employee_it/workflow.py` | 528 | Keep; it is one explicit graph with small nodes and a clear execution boundary. |
| `workflows/lifecycle.py` | 512 | Keep; durable run, approval, and event persistence share locking and sequencing rules. |
| `database/seed.py` and `database/records.py` | 445 each | Keep; both are declarative catalogs rather than deeply branching business logic. |

## Remaining complexity findings

The strict optional Ruff scan (`C901`, `PLR0912`, and `PLR0915`) reports five functions:

- `employee_it/actions.py::execute_repository_access`
- `operations/refunds.py::execute_refund`
- `security/traffic.py::TrafficProtectionMiddleware.__call__`
- the two evaluation-only fixture builders

The first three protect atomic transactions or request rejection behavior. A mechanical split would
hide the order of rollback, authorization, retry, and verification steps without reducing risk.
They remain explicit and are covered by operation, security, PostgreSQL, and browser tests. The two
fixture builders are test-data mutation switches, not production request paths; consolidating their
branches would make the scenarios less obvious. These are documented follow-up candidates rather
than silently waived findings.

## Duplication, dead code, and naming

- Ruff reports no unused imports or local variables under the project's enforced rules.
- Searches found no `TODO`, `FIXME`, `NotImplementedError`, or placeholder production bodies. Empty
  classes are intentional typed exception or declarative base classes.
- Similar customer and employee evaluation fixture code is intentional today because the domains
  mutate different records. A shared fixture framework would add abstraction without removing the
  domain-specific branches.
- Local names such as `record`, `result`, and `session` are scoped to short persistence operations.
  Public types and endpoints use domain names such as `WorkflowApproval`, `ReliabilitySummary`, and
  `EmployeeAccessWorkflowResult`; no exported catch-all `Manager`, `Helper`, or `Utils` type was
  introduced.

## Verification required for structural changes

Any future split of the transaction-heavy modules must keep the same fail-closed behavior and pass:

1. unit and workflow tests;
2. real PostgreSQL concurrency tests;
3. migration upgrade and downgrade checks;
4. security and tenant-isolation tests;
5. the Chromium approval, reliability, and Employee/IT flow.
