+++
document_id = "POLICY-RETURN-REFUND"
title = "Returned Item Refund Investigation"
version = 1
status = "active"
issue_types = ["missing_return_refund"]
source = "ResolveOps Customer Operations policy library"
effective_at = 2026-01-01T00:00:00Z
+++
# Returned Item Refund Investigation

## Purpose

This policy governs a missing refund for merchandise sent back by a customer. Treat a missing return
refund as a separate issue from a duplicate payment, even when both issues belong to the same case
and order.

## Required evidence

Confirm the return identifier, order, customer, returned line items, quantities, item prices, and
currency. The return must be in received or completed status before a refund is issued. A requested,
authorized, in-transit, rejected, or cancelled return is not eligible for execution.

Inspect all refunds linked to the return and payment. Pending, processing, and completed refunds are
active and count toward the refundable total. Failed and cancelled refunds do not consume the total.

## Refund calculation

Calculate the maximum return value from the returned quantity multiplied by the original unit price
for each returned item. The refund currency must match the order item and captured payment currency.
The new refund plus active refunds for the return must not exceed the returned items' value. The new
refund plus active refunds for the payment must not exceed the captured payment amount.

The refund must reference the exact return being investigated. Do not use a return identifier on a
duplicate-charge refund, and do not merge the financial reasoning for the two issue types.

## Execution and verification

Apply role permissions and refund approval limits before execution. Use a unique idempotency key so
a retry cannot create a second refund. After execution, perform a fresh read and verify the refund's
payment, issue, return, amount, currency, kind, and pending status. A failed verification must be
recorded and escalated instead of being presented as a successful resolution.
