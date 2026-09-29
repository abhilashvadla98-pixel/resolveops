# ADR-002: Multi-issue case model

## Context

One complaint can report both a duplicate payment and a missing return refund. These actions use
different evidence, identifiers, and policy rules.

## Decision

A case contains one or more independently tracked case issues. Workflows and actions target exactly
one issue.

## Alternatives considered

- One case per issue: rejected because it fragments one customer interaction.
- One combined case resolution: rejected because it can mix financial evidence and actions.

## Consequences

The data model is richer, while evidence, approvals, refunds, and verification stay correctly scoped.
