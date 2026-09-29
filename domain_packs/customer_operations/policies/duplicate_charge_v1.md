+++
document_id = "POLICY-DUPLICATE-CHARGE"
title = "Duplicate Charge Investigation and Refund"
version = 1
status = "active"
issue_types = ["duplicate_charge"]
source = "ResolveOps Customer Operations policy library"
effective_at = 2026-01-01T00:00:00Z
+++
# Duplicate Charge Investigation and Refund

## Purpose

This policy governs reports that an order was charged more than once. A customer report, a bank
statement description, or two interface rows by itself does not authorize a refund. The operator
must establish that two distinct payment identifiers reached captured status for the same order,
amount, and currency.

Pending authorizations and failed or voided attempts are not captured charges. They must not be
refunded as duplicates.

## Required evidence

Collect the order identifier, both payment identifiers, captured timestamps, amount, currency, and
payment status. Confirm that the payment identifiers are different and that both captures belong to
the customer order under investigation. Preserve those references as case evidence.

Before action, check every pending, processing, completed, failed, and cancelled refund associated
with the selected payment. An active refund counts against the remaining refundable amount.

## Refund decision

Mark the duplicate-charge finding confirmed only when the evidence shows two matching captured
payments and no legitimate explanation for the second capture. Refund one duplicated payment in
full. A partial duplicate-charge refund is not permitted by this policy.

Keep a duplicate-charge refund separate from any merchandise return refund on the same order. The
duplicate refund must not reference a return identifier. Never refund more than the captured payment
after active refunds are included.

## Authorization and verification

An agent may investigate but cannot issue a refund. An operator may authorize a refund up to 500
USD. An approver or the controlled system role may authorize up to 5,000 USD. Unsupported currencies
or amounts above the actor limit require separate approval.

Use an idempotency key for the action. After execution, read the new refund from the payment system
again and verify its payment, issue, amount, currency, kind, and pending status. If verification
fails, do not report success; record the failure and escalate.
