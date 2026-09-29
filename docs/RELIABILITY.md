# ResolveOps reliability model

ResolveOps separates failures by whether an action could have committed. This prevents a retry
policy from turning a temporary error into a duplicate refund, ticket, or customer message.

| Observed state | Automatic response | Execution allowed again? | Compensation |
| --- | --- | --- | --- |
| Explicit transient error before commit | Roll back, wait with capped backoff, retry | Yes, with the same identity | Transaction rollback |
| Attempt returns after its transaction deadline | Roll back, then apply the transient retry policy | Yes, with the same identity | Transaction rollback |
| `started` operation with an active lease | Wait | No | None while ownership is active |
| `started` operation with an expired lease | Reclaim the lease and continue | Yes, within the stored attempt limit | Transaction rollback |
| `executed` operation after a process interruption | Perform fresh verification | No | Manual if verification cannot establish the final state |
| `verification_failed` operation | Require an explicit verify-only recovery | No | Manual; never guess an inverse action |
| `completed` idempotent replay | Re-verify the stored resource | No | Manual if the stored result disappeared |
| Authorization, approval, business-rule, or payload error | Fail immediately | No | Transaction rollback |
| Retry attempts exhausted | Stop for manual review | No | Transaction rollback if no commit was recorded |

## Duplicate-execution boundary

The operation row has a unique idempotency key. The payload, operation type, and actor must match
on every replay. A database row lock and execution lease ensure only one caller owns an attempt.
The action write and transition to `executed` share one database transaction. Therefore a database
failure cannot commit the simulated resource without also recording that execution occurred.

External provider adapters must send the ResolveOps idempotency key to providers that support it
and persist the provider's operation handle before relying on the same recovery guarantees.

## Timeouts

The current action deadline is transaction-bound. ResolveOps measures the attempt and rolls back if
the call returns after the configured deadline. It deliberately does not start an unsafe background
thread that could continue writing after the caller has retried. Future network adapters must also
configure their HTTP or SDK timeout so a blocked provider call returns within this deadline.

## Partial failure and replanning

After a refund tool reports a verification problem, the workflow performs an independent database
read. If the refund exists, the workflow replans to `waiting_external` and monitors that refund; it
does not create another. If no matching refund exists, the workflow fails closed for review.

## Recovery and compensation

`get_recovery_plan()` reports the stored status, attempt counts, lease/backoff timestamps, safe
retry decision, and compensation strategy. Explicit `recover_*` methods only verify a resource that
may already exist. Automatic destructive compensation is prohibited for refunds and customer
communications because an inverse database write cannot prove that an external financial or
communication side effect was reversed.
