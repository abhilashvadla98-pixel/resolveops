+++
document_id = "POLICY-REPOSITORY-ACCESS"
title = "Team Repository Access"
version = 1
status = "active"
issue_types = ["repository_access"]
source = "ResolveOps Employee and IT policy library"
effective_at = 2026-01-01T00:00:00Z
+++
# Team Repository Access

## Purpose

This policy controls employee access to source repositories in the ResolveOps enterprise-system
simulators. The simulated directory and Git service must be treated as test systems, not as live
vendor integrations.

## Eligibility evidence

Before granting access, verify that the employee is active, the enterprise identity is active and
owned by that employee, multi-factor authentication is enrolled, and the linked Git account is
active. The employee must have an active membership in the team that owns the repository.

## Approval and least privilege

The target-team manager must approve the specific repository, employee identity, and requested
access level. A pending, rejected, missing, or differently scoped approval does not authorize an
access grant. Grant only the requested level and only the repository's configured directory group.

## Execution and verification

Use one stable idempotency key for the approved request. Do not create duplicate group memberships
or repository grants. After the transaction, independently read the directory membership,
repository access, request, case, ticket, and notification. Report success only when every record
matches the approved scope and has reached its required final state. Partial or conflicting state
requires manual review.
