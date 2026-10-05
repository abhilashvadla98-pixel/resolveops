# ResolveOps demo walkthrough

Two workflows share one console: customer refund complaints and employee repository access.
All business records, money movement, access grants and notices in the sandbox are synthetic.
No bank, CRM, directory or Git provider is changed.

This guide describes **version 1.4.0**, verified on the deployed sandbox on **2026-10-05**. Check the
[deployment record](PUBLIC_DEMO.md) and `/health/build` before using the
[public demo](https://resolveops-demo.onrender.com/console) as release evidence. A sleeping free
instance can take time to start. The repository quick start also runs the same synthetic workflow
locally. Open /console and wait until the workspace is connected.

## Flagship live-agent walkthrough

This is the shortest complete walkthrough. It uses fictional data but real Gemini role calls. The
normal **Investigate** action decides whether the specialist graph is needed; there is no
separate toy agent button.

1. Open **Customer Operations** and select `CASE-1001`, a combined duplicate-charge and missing-return-refund complaint.

   ![Complex synthetic case selected in the deployed console](assets/live-agent-20261004/02-complex-case.png)

2. Select **Investigate**. The supervisor routes the case; investigator and policy roles read scoped
   records; the resolution role drafts a typed recommendation; the independent critic checks evidence,
   citations and unsafe actions. The trace is persisted with real call, tool-read and token counts.

   ![Persisted five-role live-agent trace with grounded evidence](assets/live-agent-20261004/03-live-agent-trace.png)

3. Review the grounded proposal. Agent output remains advisory. Deterministic code verifies the exact
   evidence IDs, policy citations, payment target, amount and allowed action.

   ![Grounded proposal before any sensitive action](assets/live-agent-20261004/04-grounded-proposal.png)

4. Open the approval and record the explicitly simulated second-person decision. Approval is separate
   from investigation and is revalidated before execution.

   ![Human approval boundary for the exact refund](assets/live-agent-20261004/05-human-approval.png)

5. After approval, the simulator records a pending refund. The case stays open because submission is
   not settlement.

   ![Controlled action waiting for settlement](assets/live-agent-20261004/06-settlement-pending.png)

6. Select **Simulate settlement success**. A fresh provider read must confirm completion before the
   issue is resolved and a customer-response draft is shown.

   ![Fresh final-state verification](assets/live-agent-20261004/07-fresh-verification.png)

7. Open **Audit** to show the retained decisions, actors and outcomes.

   ![Audit trail for the completed deployed walkthrough](assets/live-agent-20261004/08-audit-trail.png)

The [85.28-second recording](https://github.com/abhilashvadla98-pixel/resolveops/releases/download/v1.2.1/resolveops-live-agent-walkthrough-v1.2.1.webm)
shows this complete deployed run. It proves that the configured path worked once; it does not prove
general model accuracy, availability or production payment integration.

## Customer Operations: complaint to settled refund

Use one complaint throughout. Do not investigate several cases for the same order merely to make
the demonstration busier.

1. Select **Open customer workflow**, then **+ New case**.
2. Enter customer CUST-DEMO-A, order ORD-DEMO-A and “I was charged twice for this order.” Select
   **Create case**. These are fictional records already in the sandbox. This is operator-assisted
   intake, not a live customer portal.
3. The new case stores the complaint and a rule-based classification. Intake does not confirm a
   duplicate charge, approve anything or create a refund. A support portal or help-desk adapter
   could use the same authenticated intake API; none is connected in this demo.
4. Select **Investigate**. The workflow rereads customer, order, payment and current policy records.
   Similar amounts or capture times alone do not prove a duplicate: trusted evidence must link two
   full captures to the same payable obligation. Missing or ambiguous evidence stops the action.
5. Review the proposed payment, amount, currency and policy evidence. The execution label identifies
   the mode for this run. **Rules Only** is not evidence that a live model ran. A configured
   specialist investigation can advise, but cannot authorize money movement.
6. Expect **Review the refund proposal**, including for this lower-value case. Confirm **No refund
   has been submitted**, then select **Review approval**.
7. Inspect the exact payment and amount. Enter a reason, then **Approve** or **Reject**. The sandbox
   explicitly simulates a separate approver; it is not a real financial approval. Approval rechecks
   current evidence and deterministic controls before one idempotent simulator write.
8. After approval, expect **Refund Submitted** and **Settlement is still pending**. The case remains
   in progress. A fresh read confirms the pending refund record, not settled money.
9. Select **Simulate settlement success**. A synthetic event passes through the settlement handler.
   Only completed refund state and fresh verification produce **Refund Settled**, **Final
   settlement verified** and a resolved case. The customer response is a draft for operator review;
   no real email is sent.

The seeded **D · High-value refund approval** scenario shows the same approval boundary with a
650 USD proposal, without creating a new case.

### Two additional customer workflows

These are separate business problems, not renamed duplicate-charge examples:

- **I · Partial refund amount is wrong:** the returned items are worth 120 USD and provider records
  show a completed 40 USD refund. Investigation cites the received return and prior refund, then
  proposes only the verified 80 USD balance. Human approval, idempotent submission and a final
  provider event are still required.
- **J · Cancelled order still charged:** the order is cancelled, one full 120 USD payment is
  captured against its explicit obligation, and no covering refund exists. Investigation proposes
  that remaining captured value. A non-cancelled order, partial allocation, multiple captures or
  uncertain obligation stops for review.

Open **Customer Operations**, choose scenario **I** or **J** from **Demo scenarios**, select
**Investigate**, inspect the specialist trace when live mode is available, review the exact proposal,
approve it, and simulate settlement. The case must remain open after submission and resolve only
after fresh completed-provider state. These two issue types deliberately request the bounded
specialist graph in live mode; deterministic code still owns eligibility, amount, authorization,
the write and final verification.

### Compare the three checkpoints

**Approval:** the target is PAY-DEMO-A-2 for 120 USD, not an amount chosen by the browser.
The note and decision are recorded separately from investigation.

![Pending approval with the exact synthetic payment and amount](assets/workflow-repair-20261004/customer-completed-approval.png)

**After approval:** the refund exists but settlement is pending. The visible execution mode is
Rules Only. The two buttons simulate provider events; they do not move real money.

![Submitted refund waiting for a synthetic provider event](assets/workflow-repair-20261004/customer-completed-pending.png)

**After successful settlement:** the fresh read confirms the final outcome. This is the first
point at which this refund is reported as settled.

![Completed synthetic settlement and fresh verification](assets/workflow-repair-20261004/customer-completed-outcome.png)

### Show one safety path

Use a fresh/reset sandbox, repeat the complaint-to-approval path, and choose **Simulate settlement
failure**. The case becomes escalated and explains that the provider reported a failure. An operator
must review it; the response must not say the customer received the refund. Demo controls cannot
replace a final outcome with the opposite outcome.

![Failed synthetic settlement requiring operator review rather than reporting success](assets/workflow-repair-20261004/customer-failed-outcome.png)

Alternatively, scenario E shows an authorization hold: no second captured charge means no refund
is needed.

Retry an escalated investigation only after correcting source records or supplying missing
information. Earlier attempts remain in the timeline. A timeout means the client does not know
the result: refresh and reconcile stored state before trying again.

For a confirmed **failed or cancelled** refund, a new investigation can propose a replacement.
It requires a new approval and a new attempt-specific request ID. Repeating that same new request
still creates only one refund. Pending or unknown outcomes do not permit a blind retry, and late
events for the old attempt cannot resolve or reopen the replacement attempt.

## Employee IT Operations: request to verified access

This path uses Gemini specialists for evidence-grounded investigation when live mode is enabled;
deterministic identity, approval, action and verification controls remain authoritative.

![Live v1.4.0 workspace with Employee IT available](assets/employee-it-live-20261005/01-live-overview.png)

1. Return to **Overview**, open **Employee IT Operations**, and select **New access request**.
2. Choose fictional employee EMP-2001, the ML Platform repository and **Write**. Enter “Implement
   the assigned model-serving endpoint.” The form labels employee selection as a sandbox simulation.
   Outside the demo, the authenticated identity determines the requester.
3. Submit. ResolveOps saves a request, case and ticket; no access is granted. The same receipt and
   content return the same request on a repeated submission.
4. Select **Review approval**. Check employee, repository, access level and manager, enter a reason,
   and select **Approve access**. The sandbox records DEMO-MANAGER:EMP-2000. In a normal session,
   an active, MFA-enabled identity must map to the actual current manager. An unrelated approver
   role or self-approval is not enough.
5. Select **Run safety checks and process**. The five roles plan, read the scoped IT snapshot,
   retrieve policy, propose a typed grant and independently criticize it. The control plane then
   rechecks employment, identity, MFA, team membership, manager approval, policy and existing access.
   Only read/write access is supported.
   Conflicting, inactive or partial access stops for reconciliation.
6. Inspect **Access Verified**, directory membership, repository permission, ticket and saved
   synthetic notice. A fresh read verifies the result. **Processing attempts** retains prior
   attempts and labels the newest result, including after refresh.

**Request:** select a fictional employee only in the sandbox. The form states whether the current
session will use live specialists or rules only.

![New employee request with repository, access level and business reason](assets/employee-it-live-20261005/02-new-access-request.png)

**Approval:** review the actual target repository, access level and manager before processing.

![Separate manager approval for the exact employee access request](assets/employee-it-live-20261005/03-manager-approval.png)

**Verification:** the final view retains the Gemini invocation records, explicit simulated manager,
fresh access result and newest processing attempt. Notices are saved records, not real email.

![Verified access result before the persisted role records](assets/employee-it-live-20261005/04-access-verified.png)

![Persisted model, latency, token and run records for all five roles](assets/employee-it-live-20261005/05-live-agent-trace.png)

Select ITCASE-2004 to show missing MFA stopping processing without a grant. A genuine correction to
source records can permit a new attempt without erasing the failed one. Reset before repeating the
fresh-request walkthrough.

![Missing MFA stops the request without granting access](assets/employee-it-live-20261005/06-mfa-safety-stop.png)

## Audit, evidence and limits

Open **Reliability** for recorded attempts and measured duration. Open **Audit** for actors,
decisions and outcomes. These are synthetic-system measurements, not external-provider performance.
An operator correction remains pending human review; it does not automatically become a trusted
label, policy or case outcome.

- Real application behavior: authenticated APIs, persistence, tenant scoping, approval records,
  idempotency, deterministic authorization, fresh reads and audit history.
- Simulated business systems: customer/payment records, settlement events, directory/repository
  changes, tickets and notices.
- Conditional: live specialist reasoning requires an enabled provider and a replacement credential.
  Browser tests disable provider calls. Show a saved trace from the same run before describing a
  demonstration as live multi-agent execution.

**Reset workspace** removes this session’s synthetic activity and restores its baseline. It does
not deploy code or repair a real external system.

## Media record

The [79.84-second Employee IT recording](https://github.com/abhilashvadla98-pixel/resolveops/releases/download/v1.4.0/resolveops-employee-it-live-agent-v1.4.0.webm)
was captured from deployed functional build `57691d027991bbb4c422baa4c3e723fc51ab2e2b` on October 5, 2026.
It shows one new request, separate manager approval, five Gemini roles, persisted invocation
telemetry, a deterministic access grant, fresh verification and a missing-MFA safety stop. The
records and business-system writes are synthetic; the Gemini calls are real.

The current deployment is `34e85689936a4363ae39b97b6c16359efd91a7ab`. That follow-up changed
approval copy and the mode label only; CI reran all six gates before it was deployed. The setup and
approval screenshots use the current copy. The execution and safety screenshots retain the
successful functional run instead of presenting a failed free-tier retry as working evidence.

The v1.2.1 customer screenshots above and 85.28-second recording were captured from the deployed Render
sandbox after `/health/build` reported commit `5179640c495960293a6dfa7ae1165ae351d5c184`.
They contain synthetic business records and no credentials. The video shows real Gemini role calls
and simulated business-system actions; no bank, CRM or Git provider was changed.

The older [63.2-second local workflow recording](https://github.com/abhilashvadla98-pixel/resolveops/releases/download/v1.2.0/resolveops-workflow-repair-20261004.webm)
starts after the workspace loads and shows
new customer intake, approval, pending settlement, success, failed settlement on a separate order,
employee request/manager approval/verification, an MFA safety stop and audit history. Captions
explicitly identify rules-only execution and synthetic systems. It contains no live-agent trace
or external-provider action. The separate live evaluation report on the release page records
one real model-backed success and one quota failure; it is not part of this rules-only recording.

The [existing technical recording](https://github.com/abhilashvadla98-pixel/resolveops/releases/download/v1.1.0/resolveops-technical-walkthrough.webm)
and images outside the dated workflow-repair folder are historical media from an earlier build.
Do not use them as proof of the updated intake, separate approval and settlement sequence.

The screenshots above were captured from local browser tests on 2026-10-04, visually inspected,
and copied into a dated asset folder. Original outputs remain in the ignored artifacts directory.
They are not evidence of the deployed version or live model execution.
See [Operator console](OPERATOR_CONSOLE.md) for capture commands and test coverage.
