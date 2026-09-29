+++
document_id = "POLICY-CUSTOMER-COMMUNICATION"
title = "Customer Case Communication"
version = 1
status = "active"
issue_types = ["duplicate_charge", "missing_return_refund"]
source = "ResolveOps Customer Operations policy library"
effective_at = 2026-01-01T00:00:00Z
+++
# Customer Case Communication

## Recipient validation

Send case updates only to a verified contact stored on the customer record. The case customer must
match the requested recipient's customer identifier. For email, the destination must match the
stored customer email after safe normalization. SMS is unavailable until the platform stores and
verifies customer phone numbers.

## Message content

Explain which issue is being investigated and avoid claiming that a refund succeeded before the
post-action verification passes. When a case includes both a duplicate charge and a missing return
refund, describe them as separate issues with separate evidence and actions.

Do not include payment credentials, secrets, authentication tokens, or unnecessary personal data.
Use the case and order references needed by the customer, but do not expose internal audit details.

## Delivery record

Use an idempotency key when sending a notification. Record the case, customer, channel, recipient,
message, delivery status, and timestamps. Read the notification state again after sending. If the
recipient does not match the verified customer contact or verification fails, block success and keep
an audit record of the failed attempt.
