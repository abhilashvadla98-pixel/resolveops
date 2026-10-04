# Release gates — workflow repair

Updated 2026-10-04. This supersedes the assertion that only human response review remained.
The October audit found real lifecycle, authorization and evidence defects. Historical tags,
the demo URL and old videos do not establish that current changes are deployed or validated.

## Implemented; proof must match the release commit

- New customer intake produces a supported finding and server-derived proposal without preconfirmation.
- Investigation cannot submit a refund. Approval binds current evidence, expires after 30 minutes
  and requires a different authorized reviewer.
- Submission, pending settlement, final success and failure are separate persisted states. Provider
  events update linked issues, cases and histories; retries cannot invent payment completion.
- Confirmed failed/cancelled attempts can receive a separately approved replacement with stable
  attempt-specific idempotency. Old events and historical partial outcomes remain isolated.
- Capture obligations, prior refunds, received quantities and currency are checked during investigation
  and immediately before execution.
- Source message receipts deduplicate retries; clarification continues the same case.
- New employee requests bind authenticated identity. Only the actual active, MFA-enabled manager can
  approve. Generic role and self-approval are insufficient; delegation is not implemented.
- IT attempts preserve history. Partial existing access stops in both workflow and raw action.
- Typed agent recommendations affect the normal workflow but cannot authorize it. Exact observations
  and selected policy citations are validated; critic acceptance alone is insufficient.
- Complex execution has conditional evidence/policy stops and explicit skipped roles. Simple cases
  can remain rules-only. The console reports the execution mode.
- The integrated ten-task evaluation uses application read tools and scores final business state.
  Historical contract smoke reports remain separate; expectations are never model context.

## Required release checks

| Gate | Required evidence / owner |
|---|---|
| Local regression | Full tests, browser journeys, formatting, typing, security and migrations on the final tree |
| PostgreSQL/concurrency | Dedicated test-database run; no SQLite result represented as PostgreSQL proof |
| Live AI behavior | Immutable integrated report with tools, outputs, failed attempts, usage and final state; quota limits recorded |
| Human review | Owner labels all 24 response-review rows; automated human labels are forbidden |
| Deployment | Exact build commit, healthy migrations/startup and fresh public success/failure journeys, separately measured |
| Presentation | Current screenshots and new technical recording; existing v1 media is historical |
| Secret safety | Owner revokes exposed key; replacement local only; no secrets in tracked source or artifacts |
| GitHub release | Reviewed change, clean checks on release commit, accurate metadata/links/version and no large generated data |

The public configuration deliberately disables provider inference. Enabling it is a separate
deployment decision requiring safe quota, credentials, per-visitor budgets and abuse controls.
Do not describe a rules-only public run as live multi-agent execution.

## Claims not established

Real payment settlement, customer adoption, commercial SLA, deployed AWS, arbitrary IT automation,
live memory-quality improvement and measured multi-agent superiority are not established.
