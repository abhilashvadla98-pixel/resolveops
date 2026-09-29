+++
document_id = "POLICY-CASE-ESCALATION"
title = "Customer Operations Case Escalation"
version = 1
status = "active"
issue_types = ["duplicate_charge", "missing_return_refund"]
source = "ResolveOps Customer Operations policy library"
effective_at = 2026-01-01T00:00:00Z
+++
# Customer Operations Case Escalation

## Escalation triggers

Escalate when required evidence conflicts, a source system is unavailable, the requested currency
has no configured approval limit, or the refund exceeds the authorized actor's limit. Do not bypass
a permission or approval failure by changing the actor or splitting one refund into smaller actions.

Escalate an executed action when a fresh state read cannot verify the expected resource. Preserve
the operation identifier, audit history, attempted resource identifier, failure code, and relevant
case evidence for review. Do not tell the customer that an unverified action succeeded.

## Handoff requirements

Identify the specific issue being escalated, because a case can contain multiple independent issues.
Include the applicable policy versions, evidence references, current workflow state, requested
action, approval reason, and any safe retry guidance. Do not combine a duplicate charge and a return
refund into one financial action.
