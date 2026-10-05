# Release gates — workflow repair

Updated 2026-10-05. This supersedes the assertion that only human response review remained.
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

## Recorded result — v1.4.0

Current deployed application commit: `34e85689936a4363ae39b97b6c16359efd91a7ab`.
The measured live execution below ran on functional commit
`57691d027991bbb4c422baa4c3e723fc51ab2e2b`; the later commit changed only approval copy and the
mode label.

- **Deployed Employee IT workflow:** one new request completed the normal five-role Gemini path,
  exact-action validation, separate manager approval, controlled repository grant and fresh active-access
  read. The measured run made 7 model calls and 2 scoped tool reads in 17.07 seconds.
- **CI:** all six jobs passed for the integration and validation pull requests.
- **Presentation:** six deployed screenshots and a 79.84-second walkthrough show request, approval,
  saved role invocations, verified access and an MFA safety stop.
- **Boundary:** directory, Git, ticket and notification systems are simulators. No external repository
  or employee account was changed.
- **Human review:** still 0/24. Only the owner can supply these labels.

## Previous recorded result — v1.2.1

Application commit: `5179640c495960293a6dfa7ae1165ae351d5c184`.

- **Deployed live workflow:** one `CASE-1001` browser run completed the normal five-role Gemini
  investigation, deterministic validation, separate approval, controlled refund submission, pending
  settlement, fresh final verification and audit. The 85.28-second recording is release evidence for
  that run, not a reliability or latency benchmark.
- **CI:** all six jobs passed for PR #13 and the merged application commit.
- **Presentation:** eight current deployed screenshots and the technical walkthrough show the exact
  live-agent/control-plane boundary. Historical rules-only media remains labeled historical.
- **Human review:** still 0/24. Only the owner can supply these labels.
- **Limits:** the incomplete 30-trial stochastic sample remains incomplete; no live bank, CRM,
  directory or Git-host integration is claimed.

## Previous recorded result — v1.2.0

Core release commit: `020ef9d2ecd6311d7b99f73d9030c6fb0fbe5aac`.

- **Regression:** 430 local tests passed, including ten real PostgreSQL and six Chromium tests.
  A separate no-local-configuration run passed 414 non-PostgreSQL/non-browser tests.
- **CI:** all six jobs passed on the pull request and merged main commit. The initial test-launcher
  import failure was fixed, not waived. See [PR #7](https://github.com/abhilashvadla98-pixel/resolveops/pull/7).
- **Live AI:** 30 requested, one correct completion, one quota failure, 28 unrun. Only the first
  task was attempted. The attached release reports preserve both attempts; reliability is not established.
- **Presentation:** seven new workflow screenshots and a 63.2-second rules-only recording. The
  video does not show live agent execution; the separate recorded integrated trace provides that evidence.
- **Human review:** still 0/24. Only the owner can supply these labels.
- **Deployment:** exact release build verified on Render with successful customer settlement,
  failed settlement and employee-access API journeys. The public workspace loaded its data.
  See the separately measured [deployment record](PUBLIC_DEMO.md); no deployed live AI is claimed.
- **Credentials:** the repository credential-pattern scan passed. Live tests required the local
  rotation acknowledgement. No replacement key is shipped; the owner must keep the old key revoked.

The source release does not mean every evidence gate is complete. Public inference is narrowly
enabled for complex synthetic investigations with safe budgets. Do not describe simple rules-only
runs as live multi-agent execution, and do not infer reliability from the one recorded deployed run.

## Claims not established

Real payment settlement, customer adoption, commercial SLA, deployed AWS, arbitrary IT automation,
live memory-quality improvement and measured multi-agent superiority are not established.
