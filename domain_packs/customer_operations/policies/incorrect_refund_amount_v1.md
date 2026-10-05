+++
document_id = "POLICY-REFUND-AMOUNT"
title = "Incorrect Return Refund Amount"
version = 1
status = "active"
issue_types = ["incorrect_refund_amount"]
source = "ResolveOps Customer Operations policy library"
effective_at = 2026-06-01T00:00:00Z
+++
# Incorrect Return Refund Amount

## Required evidence

Confirm the order, received return, returned quantities, original item prices, currency and every
refund already attached to the return or payment. A customer statement alone does not establish the
missing amount. Overlapping returns or quantities greater than the purchased quantity require
manual reconciliation.

## Amount calculation

Calculate the expected refund from received item quantity multiplied by the original unit price.
Subtract completed refunds for the same return. A pending or processing refund must be monitored;
do not create another refund while its outcome is unknown. If completed refunds cover the expected
value, explain that no additional refund is supported.

## Authorization and verification

Any positive remaining balance is a new typed return-refund proposal against a verified capture with
sufficient unrefunded value. It requires separate human approval, an idempotent action and a fresh
provider read. Submission is not settlement; keep the case open until final status and amount are
verified.
