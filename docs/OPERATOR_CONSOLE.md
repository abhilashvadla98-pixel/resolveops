# Operator console

The ResolveOps console is served by FastAPI at `/console`. It is a compact operations workspace for
Cases, Approvals, IT Requests, Reliability, and Audit. Business records and timelines come from the
same authenticated APIs and persistence used by programmatic clients.

The default light theme uses a compact sidebar, dense tables, thin borders, small radii, and one
restrained blue accent. Dark mode is optional. The layout intentionally avoids a marketing hero,
neon/glow styling, gradients, oversized cards, and invented fields such as owner, priority, or SLA.
Cases use server-side query/status filters and pagination. A selected case opens a three-pane
workspace for operational context, complaint/activity/timeline/final response, and evidence/AI
assessment/operator correction. Audit works globally and can be narrowed to a case.

## Demo flow

1. Run migrations and `python -m resolveops.database.seed`. The seed command also creates the
   deterministic 128-dimension demo policy index.
2. Start the API and open `http://127.0.0.1:8000/console`.
3. Choose **Try demo**. No API key is needed; the signed session can access only the synthetic demo
   tenant and expires after the configured short lifetime.
4. Submit a natural-language complaint and inspect its persisted classification. Intake never
   authorizes an action.
5. Select scenario D, start the investigation, and inspect the pending refund approval.
6. Enter a decision note and approve or reject. Approval resumes the durable workflow.
7. Inspect the decision summary, trusted workflow facts, versioned policy citations, ordered
   timeline, fresh verification, and grounded response. The case and issue statuses move with the
   workflow instead of remaining in their pre-action state. A successful path states that the
   refund record was created and independently verified, not that an external provider completed
   settlement.
8. Use scenario G to run the Employee/IT flow. It checks employment, identity, MFA, team ownership,
   manager approval, Git identity, and active policy before granting access, then reloads repository,
   group, ticket, and notification state for verification. Replaying it performs no duplicate grant.
   Use scenario H for verification recovery.
9. Choose **Reset demo** to remove prior customer workflows, IT grants, approval decisions,
   feedback, audit/reliability records, and event cursors before rebuilding the synthetic records.

Pending IT requests show **Approval required** instead of attempting execution. Use **Review
approval** to open the shared Approvals queue, enter a required decision reason, and approve or
reject. ResolveOps stores the approver, target-team manager, note, decision, and timestamp. An
approval returns the operator to the IT request with **Process request** enabled; rejection blocks
execution.

Every terminal IT workflow is also stored independently from the repository grant. Successful,
already-satisfied, and safety-stopped outcomes therefore remain visible after refresh. A blocked
request such as missing MFA becomes an escalated IT case and appears in the global audit history;
no access is granted.

The reset also creates several IT requests in different states so the queue is a real multi-record
working surface rather than a single flagship card. Submitting an operator correction persists
structured feedback in a pending review state; it does not change the case outcome or evaluation
truth automatically.

The Reliability view calculates operation outcomes and p50/p95 lifecycle duration from persisted
operation records. It also counts real retry, wait, recovery, failure, and manual-review events. The
recent-operation list drills into the stored execution sequence, while the latest HTTP trace ID is a
separate correlation key for structured server logs. Empty datasets display no samples instead of
inventing history.

The demo session represents separate synthetic duties: workflow submissions use `DEMO-OPERATOR`,
while approval decisions use `DEMO-APPROVER`. This makes the approval pause visible without granting
arbitrary tenant or real-system access. Normal authenticated requests continue to use the actor and
role from their trusted API-key identity.

## Security boundary

- Demo and operator tokens stay only in JavaScript memory; the page uses neither `localStorage` nor
  `sessionStorage`.
- The server chooses tenant and role. Request bodies cannot select either.
- Reset is accepted only from a signed demo session and affects only its configured synthetic tenant.
- Refund and access execution still passes deterministic permissions, limits, idempotency, approval,
  and fresh-state verification.
- The same-origin Content Security Policy loads no analytics, CDN scripts, or remote fonts.
- Screenshots must contain synthetic data only and must never include keys, `.env` content, account
  pages, or cloud credentials.

## Browser regression

`tests/test_browser_e2e.py` starts the actual application with a migrated and seeded disposable
database, opens Chromium, creates a complaint, runs scenario D to an approval pause, approves it,
checks synchronized case state, trusted evidence, the persisted completion timeline, and grounded
final response, inspects real reliability metrics, completes the controlled Employee/IT access
flow, proves an MFA safety stop, and verifies that reset restores both domains. CI installs Chromium
and runs this test in its own browser job. The test writes its screenshot only to a temporary test
directory.

## Current limits

The console has no enterprise SSO, live payment/CRM/directory/Git integration, shared multi-process
rate limiter, or customer-facing workflow. The small same-origin HTML/CSS/JavaScript interface does
not yet justify a separate frontend build and deployment.
