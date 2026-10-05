+++
document_id = "POLICY-CANCELLED-ORDER-CHARGE"
title = "Cancelled Order Captured Charge"
version = 1
status = "active"
issue_types = ["cancelled_order_charge"]
source = "ResolveOps Customer Operations policy library"
effective_at = 2026-06-01T00:00:00Z
+++
# Cancelled Order Captured Charge

## Required evidence

Verify that the order is cancelled, the payment reached captured status, its obligation matches the
full order total and currency, and no shipment or conflicting allocation requires review. An
authorization, pending attempt, failed payment or customer statement alone is not refundable money.

## Refund decision

Read every refund for the captured payment. Monitor pending or processing refunds instead of creating
another. Subtract completed refunds from the captured amount. Propose only the positive remaining
captured value. Multiple or partial capture allocations require a payment specialist.

## Authorization and verification

An agent may investigate and recommend, but cannot approve or execute the refund. Deterministic code
must validate the exact order, payment, amount, currency and policy. A separate human approval,
idempotent action and fresh provider read are required. Keep the case open until settlement is final.
