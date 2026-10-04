# Operator console

FastAPI serves the console at /console. Customer Operations, Approvals, Employee IT, Reliability
and Audit use the same authenticated APIs and persisted state as programmatic clients. The
same-origin HTML/CSS/JavaScript interface needs no separate frontend runtime.

This document describes current source and local synthetic tests, not confirmation that the public
deployment runs this revision. See the [walkthrough](DEMO_WALKTHROUGH.md) for operator-facing steps.

## Customer intake and investigation

**+ New case** is an operator-assisted form using POST /api/v1/cases. It stores the original
message, its rule-based classification and relevant operational references. Intake leaves findings
unconfirmed until investigation. A source-message receipt detects duplicate delivery; conflicting
content with the same receipt is rejected. Follow-up messages remain attached to the same case.

A support portal or help-desk adapter could use this authenticated API. No live CRM or public
customer portal is connected. Supported complaints are duplicate charges, missing return refunds
and combined complaints. Insufficient details require clarification or review, not invented
payment evidence.

**Investigate** rereads operational and current policy records. Similar amounts and nearby capture
times alone do not establish a duplicate: the action candidate must satisfy the trusted
payment-obligation checks. The server derives the refund target and amount; browser input is not
an authoritative refund proposal.

The execution label identifies rules-only or configured specialist execution for the current run.
Model output remains advisory. Investigation cannot submit a refund. Every eligible proposal,
including a low-value one, pauses for a separate recorded approval.

## Approval is not settlement

The approval card shows the case, issue, payment, amount, currency and reason. Approval rechecks
evidence and safety controls before the idempotent write. Rejection does not execute the action.

| State | Meaning | Next step |
| --- | --- | --- |
| Waiting approval | Proposal exists; no refund submitted | Review the target and decide |
| Refund submitted / waiting external | Fresh read confirms a pending refund, not settled money | Wait for provider status; reconcile before retrying |
| Refund settled | Completed refund passes fresh verification | Review the customer response draft |
| Needs review | Missing, conflicting or failed evidence/provider result | Inspect the reason and reconcile |

Pending demo refunds offer **Simulate settlement success** and **Simulate settlement failure**.
These synthetic events use the refund-event processor. Normal authenticated sessions cannot use
the controls. Repeating the same final event is idempotent; replacing it with the opposite outcome
is rejected. Real payment integration is not implemented, and draft responses are not sent to
customers automatically.

All issues must meet their resolution conditions before the whole case is resolved. Tracking an
existing refund must not appear as a new refund action. An authorization hold without a second
capture is a no-action result.

## Employee IT intake and authorization

**New access request** loads tenant-scoped repositories and the requesting identity. Normal
sessions can request only for the employee bound to their authenticated principal. The sandbox
allows fictional employee selection and explicitly labels it as simulation.

POST /api/v1/it/requests saves a request, case and ticket. Its required source-message receipt makes
same-content retries idempotent; conflicting content is rejected. Only read/write levels are
supported. Request submission grants no access.

The manager decision requires a note. Outside the sandbox, an approver/system role must also map
to an active, MFA-enabled enterprise identity for the current target-team manager. Unmapped
subjects, other managers and self-approval fail closed. The stored decision preserves the real
subject instead of substituting a manager ID. Demo decisions use DEMO-MANAGER:<employee>.

**Run safety checks and process** validates employment, identity, MFA, team and Git membership,
repository ownership, manager approval, active policy and current access. The public IT endpoint
is deterministic and does not call an LLM. Partial, inactive or different-level access requires
operator reconciliation, including when a caller attempts the raw action tool.

A successful simulator action creates bounded directory/repository state and a saved notice, then
verifies through a fresh read. No real email or GitHub permission is changed. Each attempt has a
new workflow ID. **Processing attempts** lists newest first; recovery after a source correction
does not overwrite an earlier safety stop. Exact existing approved access is a no-new-action
outcome, not another grant.

## Security and operation boundaries

- Demo sessions isolate synthetic data. Local tests use disposable SQLite; PostgreSQL-backed demo
  sessions use separate schemas. This is not evidence about the current cloud deployment.
- The server determines tenant and role. Bodies cannot choose either. Normal employee binding uses
  provisioned identity records; the console does not implement enterprise SSO.
- Tokens stay in JavaScript memory, not localStorage or sessionStorage.
- Demo reset affects only its synthetic workspace and restores baseline records after removing
  accumulated activity. It is not an ordinary operator action.
- Actions enforce permissions, scope, approval, idempotency and fresh checks. A timeout is an
  unknown result: reconcile persisted state before retrying.
- Reliability uses recorded operation attempts and latency samples. Empty data means no samples.
  HTTP trace IDs correlate logs; they are not proof of model execution.
- Corrections stay pending human review. They do not automatically become labels, trusted memory,
  policy or verified case findings.
- Content Security Policy loads no third-party analytics, CDN scripts or remote fonts.
- Screenshots contain only synthetic business records, never keys, secret files, account pages or
  cloud credentials.

## Browser regression and captures

The browser fixture migrates/seeds a disposable database, starts the real application and operates
it through Chromium. It explicitly disables live-agent and queued-provider execution, regardless
of the owner’s environment. These tests prove application/control-plane behavior, not live LLM
execution or an external provider connection.

- tests/test_browser_e2e.py: loaded workspace, new complaint, seeded approval, pending/settled
  refund, evidence/response, reliability, employee grants, MFA safety stop and reset.
- tests/test_customer_journey_browser.py: new complaint through separate approval and pending
  refund to completed or failed synthetic provider outcomes.
- tests/test_employee_it_browser.py: new fictional requester, separate manager simulation,
  processing and newest-attempt verification.

From the repository root, with Chromium installed in the test environment:

```powershell
$env:RESOLVEOPS_SCREENSHOT_DIR = "$PWD/artifacts/workflow-proof"
.\.venv\Scripts\python.exe -m pytest -q -m browser tests/test_browser_e2e.py tests/test_customer_journey_browser.py tests/test_employee_it_browser.py
```

The optional directory receives approval-target, pending/settled/failed refund and IT
intake/approval/verification screenshots. Without it, captures go to temporary test directories.
The artifacts directory is ignored by Git. Inspect images before promoting selected captures to
public documentation. Current deployed live-agent screenshots are in
`docs/assets/live-agent-20261004/`. `scripts/record_public_live_agent_demo.py` records the bounded
complex-case investigation, persisted five-role trace, approval, pending action, fresh settlement
verification and audit from the public sandbox. Its v1.2.1 recording is a release asset. Running it
spends provider quota and should not be used as an ordinary health check.
`scripts/record_product_demo.py` remains the rules-only local recorder; that earlier video is
historical.

## Current limits

This is a synthetic operations application with enforced controls, not a production payment or
identity service. There is no live payment/CRM/directory/Git integration, customer-facing portal,
enterprise SSO or demonstrated production load. Live model behavior requires separate trace and
evaluation evidence. More frameworks would not close those integration and evidence gaps.
