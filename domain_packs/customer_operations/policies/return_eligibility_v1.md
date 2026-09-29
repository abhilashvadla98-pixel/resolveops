+++
document_id = "POLICY-RETURN-ELIGIBILITY"
title = "Return Status and Eligibility"
version = 1
status = "active"
issue_types = ["missing_return_refund"]
source = "ResolveOps Customer Operations policy library"
effective_at = 2026-01-01T00:00:00Z
+++
# Return Status and Eligibility

## Return lifecycle

A requested return has not yet been authorized. An authorized return may be shipped, and an
in-transit return has not reached the receiving location. Received means the returned merchandise
arrived and can be inspected. Completed means the return workflow finished. Rejected and cancelled
returns are not eligible for a merchandise refund.

## Eligibility checks

Match every returned item to an original order line and verify the quantity does not exceed the
purchased quantity. Preserve the stated return reason and receiving evidence. Do not treat a carrier
scan alone as warehouse receipt.

Refund execution requires received or completed status. Once eligibility is established, use the
Returned Item Refund Investigation policy to calculate the returned value, check existing refunds,
apply approval limits, and verify the resulting refund state.
