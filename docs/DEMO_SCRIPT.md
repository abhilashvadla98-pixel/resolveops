# ResolveOps 90-second recruiter walkthrough

Before recording, start the local synthetic demo from the README, open `/console`, click **Try
demo**, and reset the workspace. Keep secrets, terminals, account pages, and real personal data out
of the recording.

## 0–15 seconds: problem and boundary

“ResolveOps investigates customer and employee operations cases. AI can plan, read allowlisted
evidence, retrieve policy, and recommend a resolution. It cannot approve, move money, grant access,
or claim completion. Deterministic software controls those decisions.”

Show the populated Cases queue and select scenario D.

## 15–35 seconds: evidence to recommendation

Start the duplicate-charge investigation. Point to the integrated Supervisor, Investigator, Policy,
Resolution and Critic trace, then show customer/order/payment evidence and versioned policy. Use a
verified live trace for the technical walkthrough; do not describe skipped provider calls as live
multi-agent execution.

## 35–55 seconds: human control and verified action

Open Approvals, enter a decision reason, and approve. Return to the case and show the idempotent
refund action plus fresh verification. Say: “The response says a simulated refund record was
created and independently verified; it never says an external provider settled money.”

## 55–70 seconds: failure behavior

Open Reliability and show the ordered attempt/recovery/verification events and trace ID. Briefly
show ITCASE-2004: missing MFA produces a durable safety stop and no repository access.

## 70–90 seconds: engineering evidence

Show the README evidence table and CI badge/run:

- 24/24 customer, 14/14 IT, and 22/22 multi-agent trajectory cases;
- 17/17 adversarial security cases;
- 151,862-record PostgreSQL scale run;
- 232/232 mixed API requests;
- 200/200 queue jobs claimed once by eight workers;
- rejected reranker experiment because latency failed the adoption rule.

Close with: “The repository includes Docker, migrations, Terraform for API/worker/RDS/Valkey,
OpenTelemetry export, recovery runbooks, and a backup/restore drill. Cloud deployment and human
response review are deliberately listed as not completed.”

## Recording checklist

- Use 125–150% browser zoom only if text remains readable; keep the full workspace visible.
- Record one continuous path instead of touring every screen.
- Do not display `.env`, API keys, provider dashboards, emails, or GitHub security settings.
- Call every integration synthetic/simulated unless it is actually connected and verified.
- Record only after the demo workspace is loaded; keep the existing 42-second clip as the teaser.
- Do not record the technical walkthrough until the exposed provider credential is rotated.
- Link the video only after replaying it and checking that no secret or personal notification is
  visible.
