## Problem

<!-- What user or operator problem does this change address? -->

## Change

<!-- Describe the smallest useful change and the affected trust boundary. -->

## Evidence

<!-- List tests, evaluation cases, screenshots, or measurements. -->

## Risk and rollback

<!-- Note remaining risk, data or schema changes, and how to reverse the change safely. -->

- [ ] Model output remains advisory; deterministic controls retain write authority.
- [ ] Tenant scope, RBAC, idempotency, and fresh verification still apply to writes.
- [ ] No credentials, real personal data, or generated large artifacts are included.
- [ ] Documentation distinguishes measured results from unverified claims.
