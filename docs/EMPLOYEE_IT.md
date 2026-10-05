# Employee and IT domain

## Flagship scenario

The reference scenario is: "I joined the ML Platform team and cannot access the source repository."
ResolveOps treats this as a controlled access case, not a chat response. It reads the
employee, enterprise identity, team membership, target repository, directory group, Git account,
approval request, IT ticket, policy, and any existing access before deciding what to do.

All directory, Git, ticket, and notification systems in this repository are local enterprise-system
simulators. They do not call GitHub, an identity provider, a ticket vendor, or an email provider.

## Data model

Migration `0008_employee_it_domain` adds persisted records for:

- employees, managers, teams, and team memberships
- enterprise identities, MFA state, directory groups, and group memberships
- Git accounts, repositories, and repository access
- access cases, scoped access requests, approval evidence, IT tickets, and notifications

The sample case is `ITCASE-2001`. Devin Chen is an active ML Platform member with an active
identity, MFA, and Git account. The team's manager has approved write access to the `ml-platform`
repository, but the required group membership and repository access are initially missing.

## Workflow and control boundary

`EmployeeAccessWorkflow` uses the shared LangGraph, retrieval, reasoning, action, reliability,
audit, security, and observability runtime. Its domain nodes are:

1. load the persisted case and linked resources;
2. deterministically check employment, identity ownership, MFA, team membership, Git account, and
   repository ownership;
3. inspect existing group and repository access;
4. retrieve the active repository-access policy with citations;
5. when live mode is enabled, run the five-role Gemini graph over scoped read tools and policy;
6. require critic acceptance and validate the exact typed repository-access recommendation;
7. require an actionable case and exact approval from the target-team manager;
8. call the shared idempotent action layer;
9. independently read and verify every final record before reporting success.

The agents cannot approve or grant access. Authorization, approval scope, eligibility, exact access
level, state changes, idempotency, and final verification are deterministic. Partial or conflicting
existing access is escalated instead of silently repaired or overwritten.

One transaction creates the missing group membership and repository access, fulfills the access
request, resolves the case and ticket, and creates the employee notification. The action is marked
complete only after a separate fresh read verifies all six results. Operation and reliability
events use the same durable audit system as Customer Operations.

## Read-only simulator API

Authenticated read endpoints are available at:

- `GET /simulator/v1/it/employees/{employee_id}`
- `GET /simulator/v1/it/cases/{case_id}`

They use the existing database-per-tenant routing. Agents receive masked employee names, email
addresses, enterprise usernames, Git usernames, and notification recipients. Roles with
`read_pii` receive the complete simulator records. Access grants have no public write endpoint.

## Evaluation

The versioned dataset at `evals/workflows/employee_it.jsonl` has 14 deterministic regression cases covering a
successful grant, grounded advisory reasoning, authorization denial, employee and identity state,
MFA, team membership, Git state, approval status and approver identity, partial access conflict,
idempotent no-action behavior, missing policy, and a manual-review recommendation.

Run it with:

```powershell
.\.venv\Scripts\python.exe -m resolveops.evaluation.run_employee `
  --output evals/workflows/employee-it-latest-report.json
```

The checked-in result is 14 of 14 cases passing. This is a local regression result over designed
cases, not a production accuracy or external-service reliability claim.

## Current limitations

- The domain has local simulators only; live vendor adapters and OAuth/application installation are
  future integration work.
- Manager approval is persisted before this workflow starts. The IT workflow does not add a second
  durable pause/resume approval because the existing scoped approval record is the
  authoritative input.
- Provisioning is synchronous and transactional in the simulator. Real directory and Git providers
  would require asynchronous status events, provider-specific reconciliation, and compensating
  procedures.
- The sample covers repository onboarding. Offboarding, periodic access review, time-limited grants,
  and broad entitlement discovery remain future cases.
