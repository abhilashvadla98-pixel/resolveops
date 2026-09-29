+++
document_id = "POLICY-PAYMENT-STATUS"
title = "Payment Status Interpretation"
version = 1
status = "active"
issue_types = ["duplicate_charge"]
source = "ResolveOps Customer Operations policy library"
effective_at = 2026-01-01T00:00:00Z
+++
# Payment Status Interpretation

## Payment lifecycle

A pending payment has been created but has not been approved. An authorized payment has reserved
funds but has not been captured. A captured payment represents a completed charge. A failed payment
did not complete, and a voided payment was cancelled before settlement.

Interfaces may display a temporary authorization next to a captured payment. Two visible rows do not
automatically mean that the customer was charged twice. Operators must compare payment identifiers,
status, amount, currency, order, and capture timestamps.

## Investigation use

Only captured payments can support a confirmed duplicate-charge finding. Pending, authorized,
failed, and voided payments must not be refunded as completed duplicate charges. Preserve the raw
status and provider reference in the issue evidence instead of changing it to fit the report.

Use the Duplicate Charge Investigation and Refund policy for the final duplicate decision, approval
limit, refund execution, and post-action verification.
