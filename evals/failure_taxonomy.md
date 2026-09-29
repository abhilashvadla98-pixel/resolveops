# Evaluation failure taxonomy

This taxonomy maps checked-in tests or evaluation cases to expected system behavior. Entries are
designed regressions, not claims about production incidents.

| Category | Representative evidence | Required behavior |
| --- | --- | --- |
| Ambiguous authorization hold | Retrieval `RET-003`; workflow ambiguous cases | Do not treat a pending authorization as a captured duplicate |
| Stale refund state | Existing-refund workflow cases | Fresh-read current refunds and do not create another |
| Currency mismatch | Billing and action validation tests | Reject before execution |
| Expired or inactive policy | Knowledge effective-date tests | Exclude it from applicable retrieval |
| Wrong policy | Required-policy workflow cases | Stop at review when the controlling policy is absent |
| Missing evidence | `duplicate_evidence_missing` tests | Do not authorize a refund |
| Malicious policy content | `test_malicious_knowledge_is_rejected_before_storage` | Reject before chunking, embedding, or storage |
| Unsupported request | Intake unsupported-complaint tests | Record unsupported intake; create no action |
| Prompt-injection complaint | Intake adversarial test | Treat text as data and classify no executable instruction |
| Malformed model citation | Invalid-reference reasoning cases | Fail closed to review |
| Approval race/replay | Approval replay and conflicting-decision tests | One decision; conflicting replay is rejected |
| Repeated webhook | Event replay tests | One state transition and one durable receipt |
| Duplicate action request | Concurrent idempotency test | One logical side effect |
| Committed action, verification timeout | Verify-only recovery test and demo H | Never re-execute; retry verification or escalate |
| Cross-tenant attempt | Authentication and webhook tenant tests | Deny without revealing tenant data |
| Unauthorized tool use | Agent/operator permission tests | Deterministic permission denial |
| Unsupported completion claim | Customer response model tests | Reject wording that claims unverified completion |

The taxonomy should grow when a new reproducible failure is added. A category without a test or
evaluation reference does not count as covered.
