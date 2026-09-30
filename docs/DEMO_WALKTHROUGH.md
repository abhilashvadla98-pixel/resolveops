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
2. Choose a case from the queue. The selected case shows the original complaint, structured issue,
   persisted evidence and history.
3. For a complete approval path, choose **Demo scenarios**, then **D · Approval pause and resume**.
4. Select **Investigate**. ResolveOps runs the normal investigation path, cites evidence and pauses
   the sensitive refund before execution.

![Customer action paused for a human decision](assets/resolveops-customer-approval.png)

5. Select **Review approval**, enter a decision reason and approve or reject it.
6. On approval, the deterministic control plane executes the idempotent simulated action, reads the
   new state independently and reports completion only when verification passes.

![Customer workflow after verified resolution](assets/resolveops-customer-workflow.png)

What this proves: evidence-grounded investigation, bounded model authority, durable human approval,
idempotent execution, fresh verification and an auditable customer response draft.

## Workflow 2: Employee IT Operations

1. Return to **Overview** and select **Open employee IT workflow**.
2. Select `ITCASE-2001` to see the approved path. Choose **Run safety checks and process** to create
   and verify the simulated repository permission.
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
