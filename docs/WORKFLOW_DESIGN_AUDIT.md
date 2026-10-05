# ResolveOps workflow audit and proposed release contract

Audit completed: 2026-10-04, America/New_York; source research began 2026-10-03.
Code inspected: `4417ca3dfad92ee0c33df03f712e5d31155863c6`.
Status: **approved design; implementation in progress in the local working tree**.
The findings below describe the audited snapshot, not the subsequently repaired source. Current
release gates and evidence are recorded in [RELEASE_GATES.md](RELEASE_GATES.md). No deployment or
live-provider success is implied by marking an implementation item complete.

This audit follows the owner's request to stop deployment changes and decide the real workflow
first. It combines source inspection, two isolated in-memory workflow reproductions, evaluation
inspection, current employer requirements, and public reference implementations. No credentials,
deployed settings, real customer records, or provider calls were changed by this audit. The existing
modified `evals/agents/verified-live-trace.json` was preserved.

## Decision in plain English

Keep two bounded services: customer billing/return investigations and employee repository-access
requests. Make the customer investigation the flagship. Finish both complete journeys before adding
scope. An agent helps interpret an unclear request, decide what evidence to read, ask a useful
question, reconcile records with policy, and explain a proposed resolution. Ordinary code owns
identity, money calculations, permission checks, approval authority, writes, and final verification.

Do not make five agents a requirement for every case. Compare a single bounded investigator with
the existing multi-role path on the same difficult cases. Retain additional roles when measured
quality or a specific separation of responsibility justifies their latency and cost. A large refund
requires stronger authorization; the amount alone does not make the investigation complex.

This is an operations application using synthetic provider adapters, not a bank, a general-purpose
IT service desk, or a claim of real customer adoption. A professional implementation can use
synthetic integrations if the boundary is explicit and the complete business lifecycle is tested.
Neither this audit nor another project's GitHub popularity establishes a hiring outcome.

## What the audit actually found

Two isolated reproductions were performed against in-memory databases, not Render:

1. A new complaint, `I was charged twice`, for `CUST-1001` / `ORD-48391` creates an undetermined,
   reported issue. Investigation reads two captured payments for 1499 USD, 60 seconds apart, but
   does not update the finding. The workflow ends with `investigation_not_confirmed`. Successful
   seeded examples bypass this missing transition by starting with a confirmed finding.
2. An approved seeded `CASE-DEMO-D` creates a refund whose status is `pending`. The workflow reports
   `action_verified`, and the issue and case become `resolved`. The response simultaneously says
   the case stays open until the refund reaches its final state. Database, UI and response disagree.

Additional source findings:

- The normal customer graph result is used as a readiness gate, but its proposed actions and
  escalation recommendation do not become the authoritative action candidate.
- The frontend chooses the last linked payment before investigation; it only constructs a
  duplicate-charge candidate, not a missing-return-refund candidate.
- `Investigate` can execute within an operator's refund limit, despite UI text saying it cannot.
- Non-demo IT approval permits an approver role, then records the team manager as `approved_by`
  without checking that the acting principal is that manager or an authorized delegate.
- The normal Employee IT endpoint performs deterministic checks without invoking an LLM. Calling
  that endpoint an identity agent or live multi-agent workflow is inaccurate.
- The five-role implementation runs a fixed specialist sequence. Supervisor delegation fields do
  not select which specialists run. Critic revision exists, but adaptive role selection is unproven.
- Current live evaluation calls Gemini but uses `OfflineTrajectoryTools`, not the application's
  real case/payment/policy tool service. Tool output includes expected-scenario labels visible to
  the model. Its pass condition checks graph shape, not successful business resolution.

Accordingly, the assertion in `RELEASE_GATES.md` that only human response review remains is not a
valid release assessment. The functional, security, and evidence gates below must also be closed.

## Priority and evidence matrix

P0 blocks a truthful release claim or a safe core workflow. P1 is required for the advertised
end-to-end product. P2 is follow-up polish or additional evidence, not permission to add platforms.
Paths and line numbers describe the audited code snapshot; they will move during repair.

| Priority / JD capability | Current evidence | Remaining gap | Exact proposed change | Proof required |
| --- | --- | --- | --- | --- |
| P0: complete customer workflow | `intake/service.py:54`, `workflows/customer_issue.py:491,685`; new-intake reproduction | New issues never become a supported finding | Derive a bounded finding from authoritative records; save source IDs and provenance; explicitly retain unknown/ambiguous findings | Submit a new complaint through the normal API and reach a correct proposal, clarification or justified no-action outcome without editing its database finding |
| P0: payment safety | `workflows/case_state.py:42,83`, `events/processor.py:144`; pending-refund reproduction | Accepted request is confused with completed refund | Separate submission verification from settlement verification; final provider events/reconciliation update the linked issue and case | Pending stays open; success closes eligible issues; failed/unknown outcomes remain actionable; duplicate and out-of-order events are safe |
| P0: authorization | `api/employee_it.py:287-353` | Generic approver becomes recorded manager | Bind principal to employee identity and actual manager/delegation; retain actual actor, scope and decision | Wrong manager, cross-tenant actor, expired delegation and self-approval denied; correct manager/delegate accepted |
| P0: useful controlled agent output | `workflows/customer_issue.py:586-711` | Critic readiness does not connect recommendations to actions | Validate typed per-issue dispositions and evidence references; honor clarification/no-action/escalation; build authoritative proposals server-side | Agent refusal or escalation cannot lead to refund; a valid supported recommendation produces the correct bounded proposal |
| P0: defensible evaluation | `scripts/run_live_agent_evaluation.py:70,124`, `evaluation/offline_agents.py:204,214` | Simulated tool contract test is presented too broadly; expectations leak | Keep it as a provider-backed contract smoke test; remove model-visible labels; add normal-workflow evaluation using seeded stores and real read tools | Saved input, tool observations, model outputs, approval events and final business state; expectations exist only in scorer |
| P1: correct financial evidence | `domain/billing.py:49`, `operations/refunds.py:125` | Two similar captures are treated as sufficient; rules differ between reads/writes | Add bounded order/payment-obligation and capture linkage; one shared evidence rule; select eligible capture on server | Authorization-only, legitimate split captures, different obligations and different currencies do not cause incorrect refunds |
| P1: return handling | `workflows/customer_issue.py:523,693`, console `app.js:115` | No return action candidate; latest-return shortcut can select wrong record | Resolve returned items and received quantities, refundable value, payment linkage and existing refunds; ask if return identity is ambiguous | New partial/full return complaints; existing refund; multiple returns; no duplicate or excess refund |
| P1: clear human control | console `app.js:112-115`, `customer_issue.py:727` | Investigate may mutate; approval toast overstates result | Make investigate read-only; expose separate proposal submission/approval; display actual returned state | No mutation from investigation; approval alone is not a settlement claim; pending/rejected/failed are visible |
| P1: actual intake and continuation | `intake/service.py`; Employee IT routes | Repeated complaint posts create cases; no clarification continuation; IT starts with fixtures | Add source/message idempotency and reply-to-case continuation; small authenticated IT intake in the existing UI | New customer and employee requests can finish; duplicate posts do not create duplicate work; missing information can be supplied and resumed |
| P1: truthful routing | `orchestration/domain.py:89`, `graph.py:151`, `customer_issue.py:660` | Fixed roles and amount trigger described as adaptive | Explicit complexity signals and bounded optional-role routing; retain fixed pipeline label until routing works | Simple case skips unnecessary roles; ambiguous multi-issue case selects justified roles; routing decision visible and tested |
| P1: supported citations/context | `agents/runtime.py:275,394` | All retrieved citations replace selected citations; shape checks are not factual grounding | Preserve raw selected citations; validate IDs, versions and statement support against scoped observations; server-bounded timestamps and context | Fabricated/mismatched evidence, stale policy, irrelevant citations, truncated required data, cross-tenant data and injected instructions fail safely |
| P1: durable operator recovery | `api/employee_it.py:397`; synchronous customer execution | Repeat IT attempt can retain old summary; unresolved stops lack complete continuation | Preserve attempt history and update latest projection; resume same case after new facts; reuse existing persistence/queue where needed | Refresh/restart during work; model timeout; correct MFA then retry; partial grant reconciliation; no duplicate writes |
| P1: human review and feedback | Review interface; `evals/feedback/owner-corrections-v1.jsonl` | 24 labels still require owner work; feedback provenance must remain honest | Keep labels empty until owner reviews; verify existing correction and regression chain, do not invent another human approval | Owner-reviewed rows; source correction -> review -> dataset hash/version -> experiment -> regression report |
| P1: deployed AI evidence | Public synthetic demo and separate local trace | A local provider smoke does not prove live deployed workflow | Show execution mode per run; configure rotated credential only after safe runtime gates and owner direction; validate one deployed normal trace | Deployed build SHA, model/usage, real application tool sources, outcome and environment recorded separately from local results |
| P2: efficiency/memory benefit | ADR-007; eight deterministic memory pairs | No quality benefit proven for five roles or memory | Paired single-agent/multi-role and memory/no-memory studies with identical tasks and held-out expectations | Business success and safety alongside latency, model/tool calls, tokens and known/unknown cost; no benefit claim without measured benefit |
| P2: reproducible presentation | Existing docs, screenshots, teaser, walkthrough | Some broad claims exceed evidence; artifacts can drift | Update README and release gates after verified fixes; immutable run reports, one workflow diagram, current screenshots/video | Every public claim points to matching versioned evidence; no stale success metrics or unimplemented integration claims |

## Service 1: customer billing and return investigations

### Supported business problems

- A customer believes they were charged twice.
- A customer has returned an item but has not received the expected refund.
- One complaint contains both issues, an existing refund, or conflicting information.
- A customer needs a status explanation, not another refund.

Other complaint categories should be explicitly unsupported and routed to an operator. Do not
invent shipping, cancellation, fraud, warranty, or dispute-resolution capabilities merely to widen
the demo.

### A concrete proposed flagship, using synthetic records

Customer message: "I returned the headphones, see two charges, and support said my refund started.
Please check before charging or refunding me again."

This is a proposed acceptance scenario, not a measured result. Seed an order containing 120 USD
headphones and a 30 USD accessory, total 150 USD. Two separately identified 150 USD captured
payments map to the same 150 USD payable obligation; there is no separate shipment obligation.
The headphones have a received return, and an existing 120 USD refund against the first capture
is pending. The second capture has no refund.

Expected reasoning: investigate the charge and return issues separately. Do not create a second
return refund. If authoritative obligation/capture records and current policy confirm that the
second capture is extra, propose refunding that capture for 150 USD. Show the existing 120 USD
refund as pending. After both refunds succeed, net captured value is 30 USD, matching the retained
accessory. All arithmetic is checked by code, not accepted from generated text.

Counterexample: two 75 USD captures allocated to separate fulfilled parts of a 150 USD order are
not automatically duplicates. If the required allocation/obligation evidence is unavailable, ask
for investigation or escalate; do not promote equal-looking transactions to a confirmed finding.
Payment providers can support multiple captures, so the simplistic equality heuristic is
insufficient. [Payment capture documentation](https://developer.payments.jpmorgan.com/docs/commerce/online-payments/capabilities/online-payments/how-to/auth-and-capture-payment)

### The complete proposed customer journey

| Step | Who acts and what happens | Visible result / next step |
| --- | --- | --- |
| 1. Receive | Customer submits a complaint in a small sandbox intake view; operator may also enter one on the customer's behalf. Source and message ID are saved. | Receipt and case ID. Clearly identify demo personas and synthetic records; do not imply a live email/CRM integration. |
| 2. Link safely | Backend derives tenant/persona from the session, checks order ownership, deduplicates the message. | Correct order and conversation appear in the operator queue. Arbitrary IDs cannot grant access. |
| 3. Understand | Bounded investigator identifies supported issues and missing information from the message and linked records. Straightforward structured requests may use rules. | Separate issue list, or a specific question such as which returned item. A reply resumes this case, not a new one. |
| 4. Gather evidence | Agent selects permitted read tools for order obligations, captures, returns, prior refunds and support events. Tools enforce scope. | Evidence timeline with exact IDs, amounts, status and observation time; read-only investigation cannot move money. |
| 5. Check policy | Retrieve relevant active policy with tenant, version and effective date. Extra policy role only when justified. | Selected supported citations; missing/conflicting policy stops the proposal with an owner and next step. |
| 6. Propose | Agent recommends per-issue refund, wait, explain/no-action, request-information or escalate. Code validates evidence and calculates a permitted candidate. | Proposal lists exact capture/return, amount, reason, evidence and consequences; existing refund is handled without duplicating it. |
| 7. Review | Operator reviews proposal. Higher-risk/value cases require the separately authorized approver defined by policy. | Approve, reject or edit-and-revalidate. Decision binds actor, proposal hash, policy/evidence versions and expiry. |
| 8. Submit | A separate explicit action invokes deterministic authority checks and an idempotent provider adapter. Re-read state immediately before execution. | Submission ID or known failure. Unknown result after timeout goes to reconciliation, never a blind second payment write. |
| 9. Verify submission | Fresh adapter read confirms refund request identity, amount, target and accepted status. | "Refund submitted; settlement pending." Request acceptance is not money arriving in a customer's account. |
| 10. Track settlement | Authenticated provider event or controlled reconciliation reports final status. Demo uses a clearly labeled simulator through the same handler contract. | Pending remains open; failure shows recovery owner; successful settlement closes only the eligible issue. |
| 11. Communicate | Grounded customer update states what happened and what remains. Persist draft/delivery status separately. | In-demo customer sees the update. Do not claim email or help-desk delivery unless that connector actually sends it. |
| 12. Audit/learn | Retain concise tool events, sources, decisions, approvals, failures, usage and outcome. Operator corrections enter a human-reviewed dataset. | Replayable explanation, not hidden chain-of-thought; correction can become a regression test after genuine human review. |

Refund creation and final status must remain separate; provider documentation includes pending and
failed refund states. [Stripe refund lifecycle](https://docs.stripe.com/refunds)

## Service 2: employee repository-access requests

Scope: repository access for an existing employee. Not password resets, general hardware support,
new employee onboarding, or broad autonomous infrastructure administration.

1. Employee submits a request tied to their authenticated identity: repository, intended work,
   permission level and, where policy requires it, duration.
2. An optional assistant interprets an unclear request and asks for missing details. A clear form
   needs no LLM. Identity, employment status and MFA are never decided by an agent.
3. Read current employee, directory identity, MFA, team, repository ownership and existing grants.
   Backend enforces tenant and resource scope on every read.
4. Calculate the minimum allowed grant from policy. Already-sufficient access returns a verified
   no-op. Missing MFA identifies a remediation step and keeps the request resumable. An inactive
   employee is denied. Unsupported/conflicting ownership goes to a named operator.
5. The actual manager or explicitly authorized delegate reviews the exact requested grant. Store
   the authenticated actor, delegation if used, policy version and decision. Do not substitute a
   manager's ID for whoever clicked approve.
6. An authorized provisioning action grants only the approved permissions with a stable
   idempotency key. Revalidate identity, policy and approval before the write.
7. Independently read directory-group membership and repository permission. If one write succeeds
   and the other does not, record partial success and reconcile; do not announce completion.
8. Update the ticket and requester-facing status. Record whether a notification was only displayed
   in the sandbox or actually delivered. Show every attempt and the latest verified outcome.

This is a useful second workflow because it exercises a different authorization boundary, not
because it increases the agent count. The existing deterministic employee path should be labeled
accurately until any optional assistant is implemented and verified.

## Data, authority, and feature boundaries

Use a bounded version of the domain data already present, not a new data platform:

| Record | Why needed / source of authority |
| --- | --- |
| Message receipt and conversation | Source ID, authenticated subject, case linkage, replies and intake deduplication |
| Order / line item / payable obligation | What is actually owed; prevents confusing legitimate split charges with duplicate collection |
| Payment / capture allocation | Distinct provider capture ID, obligation, amount, currency and lifecycle status |
| Return and received items | Which item/quantity was accepted and what is eligible, instead of blindly selecting the latest return |
| Refund and allocation | Which payment/return it covers; pending, completed and failed values prevent double refunds across cases |
| Evidence snapshot | Scoped source IDs, source version and observation time; distinguishes observation from a model assertion |
| Action proposal / approval / attempt | Exact requested action, actual approver, versioned validity and idempotent operation history |
| Employee / identity / team / repository / grant | Authoritative employment, MFA, manager ownership and present permissions |
| Policy and reviewed memory | Policy is authoritative within version/scope; reviewed memory remains advisory and cannot override policy |

All public data remains synthetic. Demo payment/access providers are simulations, with explicit
labels on actions and events. Live LLM inference, simulated business systems and a cloud-hosted UI
are three different claims. Each run must expose its actual mode: live model, rules-only, or replay.

Features earn inclusion as follows:

- Agents: uncertain language and multi-source investigation. Not arithmetic, permission checks or
  prefilled button flows. Tool/model calls must affect an inspectable recommendation.
- Multiple roles: independent policy work, separable issue investigations or a useful critic.
  Validate utility before defaulting to extra calls. Do not use refund size as the only trigger.
- Retrieval: current policy evidence with citations, freshness and access control. Not decorative
  documents that never affect the outcome.
- Human review: a real decision needed by policy or uncertainty, with reject/edit/resume behavior.
  Not an approval button that always ends in a generic success toast.
- MCP and typed skills: retain existing bounded capabilities and real consumer evidence. Do not add
  another integration framework. Test denial and consumer failure; do not describe every adapter
  as an external production integration.
- Reviewed memory: reuse approved operational lessons only when tenant/version/expiry checks pass.
  No arbitrary generated text becomes trusted knowledge; benefit is presently unproven.
- Durable execution: long work survives refresh/restart, and failures can be resumed/reconciled.
  Reuse existing persistence/queue facilities before introducing infrastructure.
- Observability: helps explain bad outcomes and measure cost/latency, not just displays agent names.
- No new Kubernetes, Kafka, vector databases, fine-tuning, GraphRAG, agents or frontend framework.

## Acceptance tests before recording the release walkthrough

Every happy-path test starts from a new intake, not a fixture with a preconfirmed finding. Fixtures
provide source records; the application must produce the finding, proposal and final state.

| Test | Required observable result |
| --- | --- |
| New duplicate complaint | Evidence-derived proposal; correct capture; authorized execution; pending then final verified state |
| Authorization versus capture | Explain temporary authorization when supported; do not refund an uncaptured hold |
| Legitimate split capture | No duplicate refund merely because two captures share an order/amount |
| Partial/full return | Correct received items, currency, payment and remaining eligible amount |
| Combined charge + return | Separate issues; shared payment limits; no overlapping or duplicate refund |
| Prior refund in another case | Link existing refund and monitor; no new refund against the same obligation |
| Ambiguous message | Ask a specific question; reply continues the same case and updates evidence |
| Duplicate intake/retry | One receipt/case/action as appropriate; stable business idempotency, not a new write key per click |
| Wrong tenant or manipulated ID | Read and action denied before sensitive data is exposed |
| Missing/stale/injected policy | Safe stop with reason and recovery; retrieved instructions cannot change tool permissions |
| Unsupported or fabricated agent output | Proposal rejected; no authorization bypass from critic acceptance or invented citations |
| Human rejection/edit | No write on rejection; edited proposal must be revalidated and reapproved when required |
| Evidence changes after approval | Approval invalidated or proposal re-evaluated before mutation |
| Network loss after provider write | Unknown result reconciled by stable operation key; no duplicate refund |
| Settlement failure or reordered event | Case stays open or enters recovery; old events cannot regress a newer authoritative state |
| Model quota/timeout | Visible failure and safe continuation; rules-only fallback never pretends to be a live agent run |
| New IT request | Requester identity, correct manager, least privilege, fresh final-state verification |
| Wrong IT approver/self-approval | Denied unless a documented policy explicitly permits the actor and action |
| MFA fixed after stop | Resume same request; new attempt visible; stale failed summary not retained as latest |
| Partial IT provisioning | Truthful partial state, safe reconciliation and verified completion or explicit manual recovery |

### Evaluation that can support an AI claim

Keep deterministic tests as fast regression tests. Separately:

1. Build 10 difficult held-out tasks around these real records and workflows. Expected outcomes,
   required evidence and forbidden effects belong only in the scorer, never model input.
2. Run three integrated smoke cases first. Use the normal application tools and controller, not
   `OfflineTrajectoryTools`. In the test harness only, simulate authorized review and provider
   events; this is not human-labeled evaluation and must be named accordingly.
3. Run 10 tasks x 3 trials with the live provider when free quota permits. Record every attempted
   trial, including quota/provider failures, and report attempted/completed/correct counts.
4. Compare rules-only coverage, single-agent and multi-role approaches under comparable budgets.
   Thirty trials per AI configuration means 60 paired-comparison trials, not 30 total. Stage this
   within available free quota; do not enable billing or claim a comparison that was not run.
5. Score correct business outcome, relevant evidence/citations, requested clarification, safe
   escalation, allowed tool use, correct approval, actual writes and final state. Do not require an
   exact tool sequence unless order is necessary for safety.
6. Report per-role/end-to-end calls, tokens and latency; cost stays unknown if pricing or usage is
   unavailable. Label averages/percentiles from small samples as descriptive, not production SLOs.
7. Use immutable reports with code revision, dataset hash, prompts/schema versions, provider/model,
   environment and execution mode. Preserve the original failed runs and separate smoke evidence.
8. Complete 24 response labels through actual owner review. Keep memory benefit and response
   quality unvalidated until their corresponding tests/reviews exist. A deterministic memory
   comparison whose provider ignores context proves plumbing, not improved model reasoning.

The inspected standalone successful trace proves provider-backed orchestration with stubbed tool
responses. It does not prove normal case resolution or Render behavior. The existing 30-trial
report must not be replaced by one successful smoke result.

## Implementation order and stop conditions

1. **Repair authority and state first.** Add failing reproductions for new complaints, pending
   settlement and incorrect IT approvers; repair these and the conflicting UI claims. Finish
   server-derived duplicate/return proposals. No new agent marketing while these fail.
2. **Finish the two user journeys.** Add bounded intake/clarification, separate investigation from
   action, correct approval binding, visible final status and resumable failure paths in the
   existing app. Use synthetic providers through their actual adapter contracts.
3. **Make reasoning useful.** Connect typed recommendations to validated proposals; validate
   citations and evidence; implement only justified conditional role routing. Keep simple-path
   baseline and multi-role comparison honest.
4. **Prove behavior.** Run deterministic scenarios, then integrated provider trials within quota,
   then owner response review. Review existing feedback provenance instead of inventing labels.
5. **Verify deployed mode.** After owner-authorized credential setup, run the real deployed normal
   path with bounded tools and synthetic records. Record deployment revision, cold/warm latency,
   failures and limits. Do not mix these measurements with local tests. AWS remains reference.
6. **Refresh public evidence.** Short README, one architecture diagram, a new-intake flagship,
   screenshots at meaningful states, one 60-90 second verified technical video plus existing
   teaser, measured results, tradeoffs, limitations and working links. Audit release/CI/license,
   secret/large-artifact exclusions, repository metadata and profile pin without faking history.

The next coding slice after this design is accepted is step 1, not another deployment switch or
another framework. A passing test count does not close a release gate unless the tested behavior
matches that gate. Existing test coverage is useful but does not establish live AI reliability,
real business adoption, or production scale.

## Questions a technical interviewer should be able to ask

- How did this complaint enter the system, and who can see it?
- Why is this a duplicate rather than a legitimate second capture?
- Why did AI help here, and what happens without it?
- Which actual model/tool calls happened in this specific demo?
- How does a recommendation change the validated proposal without authorizing its own write?
- Who approved it, and what if the facts changed after approval?
- What if the provider processed the refund but the response was lost?
- Why does pending not mean resolved, and how is final status learned?
- How do I create a new case, correct missing information and recover from failure?
- What did the baseline comparison measure, and which claims are still unverified?
- Which systems are simulated, which are external, and what deployment was actually measured?
- What bug did an operator report, and which real reviewed test now prevents it?

Prepare answers by demonstrating these transitions, not memorizing framework names. AI-assisted
development is not itself a defect: some employers explicitly ask how candidates use it. Ownership
means understanding the code, testing it, defending tradeoffs, and accurately stating contributions.
Do not promise that work is human-only or hide AI assistance to imply experience that did not occur.

## Research: current employer requirements

Twelve distinct employer descriptions were checked on 2026-10-03. Greenhouse pages included full
descriptions and application forms; five Ashby descriptions were verified through each employer's
current public job-board API because their rendered pages were JavaScript shells. These are
capability references, not a claim that the owner meets their location, seniority or work-authorization
requirements. Listings can close after the audit date.

| Employer / role | Relevant requirement and implication |
| --- | --- |
| [PlayStation: AI Engineer](https://job-boards.greenhouse.io/sonyinteractiveentertainmentglobal/jobs/6007946004) | Commerce/support workflows, typed tools, human review, evidence freshness, evaluations, cloud delivery. The business domain is relevant; prove its complete operation. |
| [Sierra: Agent-Retail engineer](https://jobs.ashbyhq.com/Sierra/c729c633-0376-436e-8f2b-1501088b85b0) | Integrate order/return systems and own agents through deployment/iteration. Verified in [current board API](https://api.ashbyhq.com/posting-api/job-board/Sierra). |
| [LangChain: Agent Systems engineer](https://jobs.ashbyhq.com/langchain/eadd2a71-47fc-483b-948f-4b2384f7f93f) | Debug traces, find silent failures, create regressions and measure business outcome/cost/latency. Verified in [current board API](https://api.ashbyhq.com/posting-api/job-board/langchain). |
| [Decagon: Safety research engineer](https://jobs.ashbyhq.com/decagon/f84db19b-8de3-49d6-a954-c9ee2e365956) | Unsafe tools, injection and policy failures need adversarial tests and measured mitigations. This role includes research scope beyond this application. [Board API](https://api.ashbyhq.com/posting-api/job-board/decagon) |
| [Gamma: AI Engineer](https://jobs.ashbyhq.com/gamma/6ed26f6b-bb17-41a5-8f63-f1901554cb6b) | Product quality, feedback-derived tests, data preparation, uptime/cost/latency. [Board API](https://api.ashbyhq.com/posting-api/job-board/gamma) |
| [Material Bank: Applied AI Engineer](https://job-boards.greenhouse.io/materialbank/jobs/7732615003) | Public work plus contribution and outcome; polished product and architecture tradeoffs. Application distinguishes deployments used by real users from prototypes. |
| [Ombud: Senior Full Stack AI Engineer](https://job-boards.greenhouse.io/ombud/jobs/8599080002) | Application asks about a shipped LLM feature, current customer value, reliability, orchestration performance and eval release gates; also asks about AI-assisted development. |
| [Schonfeld: AI Engineer](https://job-boards.greenhouse.io/schonfeld/jobs/7843962) | Reusable agent infrastructure, MCP, skills, entitlements and observability. These capabilities matter when genuinely exercised. |
| [CodeRoad: Senior Agentic AI Engineer](https://job-boards.greenhouse.io/coderoad/jobs/4375543009) | API/MCP tools, human review, task-success measures, injection controls and cloud operation. Location/seniority constraints apply. |
| [CoreStory: AI Engineer](https://job-boards.greenhouse.io/corestory/jobs/4984207007) | Coherent product integration, evaluation, latency/cost comparisons and public verifiable work. |
| [Implicit: Applied AI Engineer](https://job-boards.greenhouse.io/implicit/jobs/8039713) | Support-domain knowledge, retrieval quality, evaluation and well-tested reliable Python services. |
| [Sable: Applied AI Engineer, Evals](https://jobs.ashbyhq.com/sable/36addef7-4840-4a5e-bbcb-69502776801c/) | Defensible task metrics and realistic simulation; different product domain but relevant evaluation discipline. [Board API](https://api.ashbyhq.com/posting-api/job-board/sable) |

Synthesis, not a hiring guarantee: useful shipped behavior, explicit controls, measurable quality,
reliable operation and clear explanation recur across these descriptions. More agent names do not
substitute for those capabilities. A synthetic project cannot claim actual customer usage or
commercial results without additional real evidence.

## Research: reference projects and engineering practice

| Primary reference | Useful pattern | Boundary of the comparison |
| --- | --- | --- |
| [OpenAI customer-service demo](https://github.com/openai/openai-cs-agents-demo) | Visible conversation, specialist tools, handoffs and complete example journeys | Explicit demonstration; business tools include mocks. Not proof of production operation or that a candidate was hired. Do not copy its frontend/framework unnecessarily. |
| [Sierra tau2-bench domain design](https://github.com/sierra-research/tau2-bench/blob/main/src/tau2/domains/README.md) | Separate task expectations, policy, tools and database state; evaluate outcomes, not agent names | Research simulation, not a deployed customer service product. Transfer evaluation discipline, not benchmark leaderboard claims. |
| [LangGraph support workflow guide](https://docs.langchain.com/oss/python/langgraph/thinking-in-langgraph) | Explicit workflow states, human review, checkpoint/resume and different recovery paths | Official design example, not independent proof of ResolveOps reliability. |
| [Anthropic support quickstart](https://github.com/anthropics/anthropic-quickstarts/tree/main/customer-support-agent) | Contextual retrieval and source visibility | Labeled prototype; older setup/model examples need separate checking before reuse. |
| [Individual support-agent repository](https://github.com/Amankhan1009/customer-support-agent) | Hybrid rules/LLM, conversation state and explicit free-hosting limitations | Author's public implementation, not independently verified production adoption or hiring evidence. |
| [Anthropic: building effective agents](https://www.anthropic.com/engineering/building-effective-agents) | Start with the simplest adequate approach; distinguish fixed workflows from dynamic agents; justify complexity | Engineering guidance, not proof that a specific architecture improves this dataset. Compare alternatives experimentally. |

The proposed workflow above records the design decision drawn from these references and the
observed defects before repair. See [release gates](RELEASE_GATES.md) for subsequent implementation,
test and deployment evidence; this audit itself is not a passing evaluation or deployment record.
