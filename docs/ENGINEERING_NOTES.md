# Engineering notes

These notes record decisions made while building ResolveOps. They are not production incident
reports, and they do not claim experience from a live deployment.

## Runtime compatibility

**Initial assumption →** use the newest locally available Python runtime.  
**Discovered problem →** the workflow and persistence ecosystem was not consistently compatible
with Python 3.14.  
**Decision →** standardize the application, CI, and container on Python 3.12.  
**Consequence →** less novelty, but one supported runtime across development and deployment.

## Money is not a float

**Initial assumption →** basic numeric fields would be enough for the first domain model.  
**Discovered problem →** binary floating-point is unsuitable for exact refund comparisons and
idempotency payloads.  
**Decision →** represent money with `Decimal` in domain models and fixed-precision `NUMERIC` in the
database.  
**Consequence →** explicit conversion at boundaries, in exchange for exact financial rules.

## Two payment rows are evidence, not proof

**Initial assumption →** two similar payments could be labeled a duplicate.  
**Discovered problem →** a pending authorization can appear beside a captured payment, and repeated
interface rows can refer to the same payment.  
**Decision →** require different payment IDs, matching order/amount/currency, and captured status;
the final finding remains a persisted operator/workflow decision.  
**Consequence →** more review paths, but fewer unsafe refunds.

## One complaint can contain several issues

**Initial assumption →** a case could map directly to one resolution.  
**Discovered problem →** a customer can report a duplicate payment and a missing return refund in
the same message, while each has different evidence and refund rules.  
**Decision →** a `Case` owns independent `CaseIssue` records. Duplicate-charge refunds never carry a
return ID, and return refunds must carry the exact return ID.  
**Consequence →** slightly richer persistence, but clean action and audit boundaries.

## Advice is separated from authority

**Initial assumption →** model reasoning could help interpret evidence and policy.  
**Discovered problem →** useful language synthesis does not provide authorization, exact financial
calculation, idempotency, or proof that a side effect happened.  
**Decision →** the model returns a bounded structured assessment. Deterministic code owns
permissions, limits, state transitions, action execution, and fresh-state verification.  
**Consequence →** the workflow remains useful with no model configured and fails closed when model
output is malformed or unsupported.

## Fast tests and real persistence checks serve different purposes

**Initial assumption →** one database test strategy might be enough.  
**Discovered problem →** SQLite gives fast isolation but cannot prove PostgreSQL locking,
transaction, enum, or checkpoint behavior.  
**Decision →** keep most tests on isolated SQLite databases and run migrations, durable workflow
restart, and concurrency checks against a dedicated PostgreSQL test database.  
**Consequence →** quick local feedback plus a smaller, slower integration suite with an explicit
environment requirement.

## The console stays in the application service

**Initial assumption →** a separate frontend could make the interface look more substantial.  
**Discovered problem →** the operator console is small, same-origin, and tightly coupled to a modest
set of operational APIs. A second build and deployment would add more failure modes than value.  
**Decision →** use accessible HTML, CSS, and JavaScript served by FastAPI.  
**Consequence →** no frontend framework ecosystem, but one deployable unit and a smaller security
surface.

## Recovery verifies before it repeats

**Initial assumption →** retrying a failed action was the natural recovery path.  
**Discovered problem →** a provider/database action can commit and then lose its verification
response. Re-executing could duplicate a refund or notification.  
**Decision →** persist operation state and idempotency keys; after a possible commit, recovery is
verify-only.  
**Consequence →** some workflows wait or escalate instead of appearing instantly successful, while
the side effect remains at-most-once logically.
