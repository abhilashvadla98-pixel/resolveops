# ResolveOps demo walkthrough

Open the [live synthetic demo](https://resolveops-demo.onrender.com/console). It loads fictional
customer and employee records automatically. A sleeping free instance can take about one minute to
wake; the page shows that startup state instead of presenting an empty product.

## Start here

![Two workflow choices on the ResolveOps overview](assets/resolveops-overview.png)

Choose one of the two product paths:

1. **Customer Operations** handles an external complaint from intake through verified resolution.
2. **Employee IT Operations** handles an internal repository-access request from identity checks
   through a verified least-privilege grant.

The records are synthetic and resettable. No payment, identity, repository or ticket vendor is
changed by this public demo.

## Workflow 1: Customer Operations

1. Select **Open customer workflow**.
2. The **Selected case data journey** explains the five stages. Its first stage identifies whether
   the complaint is a seeded support example or an operator/API submission.
3. To prove intake, select **+ New case**, enter a complaint and create it. The case is persisted and
   classified, but intake does not authorize any action.
4. For the flagship path, choose **Demo scenarios**, then **D · High-value refund approval**.
5. Select **Investigate**. ResolveOps loads the customer, order, payment and current policy evidence.
   Complex cases enter the normal five-role graph; any model result remains decision support.
6. The workflow pauses before the proposed 650 USD simulated refund. Confirm that **Action
   recorded** and **Outcome verified** are still incomplete.

![Customer action paused for a human decision](assets/resolveops-customer-approval.png)

7. Select **Review approval**, enter a decision reason and approve or reject it. The demo uses a
   separate approver identity so the submission and decision remain distinct audit events.
8. On approval, deterministic controls execute one idempotent write to the payment-provider
   simulator. ResolveOps then performs a separate fresh read and reports completion only when the
   stored state matches the approved action.
9. Confirm all five data-journey stages are complete. Inspect the policy citations, ordered
   timeline, verification record and draft customer response.

![Customer workflow after verified resolution](assets/resolveops-customer-workflow.png)

What this proves: persisted intake, evidence-grounded investigation, bounded model authority,
durable human approval, idempotent execution, fresh verification and an auditable response draft.

## Workflow 2: Employee IT Operations

1. Return to **Overview** and select **Open employee IT workflow**.
2. Select `ITCASE-2001` to see the approved path. Choose **Run safety checks and process** to create
   and verify a permission in the repository-access simulator.
3. Select `ITCASE-2002` to see a durable manager-approval pause. Use **Review approval**, record the
   reason, approve it, and then process the request.
4. Select `ITCASE-2004` to see the safety path. Missing MFA stops the request and no access is
   granted.

![Employee identity and repository-access workflow](assets/resolveops-employee-it.png)

What this proves: identity and employment checks, MFA enforcement, separate manager approval,
least-privilege controls, idempotent access changes and a fail-closed path.

## Verification and audit

Open **Reliability** after an operation. The record shows the attempt, duration, result, recovery
events and verification. Open **Audit** to see who did what, to which case and with what result.

![Persisted reliability and verification evidence](assets/resolveops-reliability.png)

Use **Reset workspace** to restore the same baseline for the next walkthrough.

## What is real and what is simulated

- Real: API boundaries, persistence, tenant scoping, workflow state, approval records, idempotency,
  authorization checks, read-after-write verification, audit history and browser regression.
- Simulated: customer CRM records, payment/refund provider, employee directory, repository access,
  tickets and notifications.
- Optional and provider-dependent: Gemini-backed specialist reasoning. A provider timeout or failed
  evidence contract stops before approval or execution.

The [technical walkthrough](https://github.com/abhilashvadla98-pixel/resolveops/releases/download/v1.1.0/resolveops-technical-walkthrough.webm)
is a recorded, dated run with a verified specialist trace. The public demo remains useful without a
model key because its safety and action-control path is deterministic.
