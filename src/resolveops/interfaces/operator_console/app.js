"use strict";

async function simulateSettlement(button) {
  button.disabled = true;
  try {
    await apiFetch(`/api/v1/demo/refunds/${encodeURIComponent(button.dataset.refund)}/status`, {
      method: "POST", body: { status: button.dataset.status },
    });
    await selectCase(state.selectedCase.case_id);
    await Promise.all([loadCases(), loadReliability(), loadAudit()]);
    showToast(button.dataset.status === "completed" ? "Synthetic settlement received and verified." : "Synthetic failure received. The case requires recovery.");
  } catch (error) { showToast(error.message, true); button.disabled = false; }
}

function renderClarification() {
  let panel = byId("case-clarification");
  if (!panel) {
    panel = document.createElement("details"); panel.id = "case-clarification"; panel.className = "record";
    byId("detail-complaint").parentElement.appendChild(panel);
    panel.innerHTML = `<summary>Add customer information / select a return</summary><p>Continue this case with a customer reply. Reject any pending proposal before changing its evidence.</p><form id="clarification-form"><label>Customer reply<textarea id="clarification-message" required maxlength="2000" rows="3"></textarea></label><label>Return ID (only if needed)<input id="clarification-return" maxlength="100"></label><button class="secondary-button" type="submit">Save reply</button></form>`;
    byId("clarification-form").addEventListener("submit", async (event) => {
      event.preventDefault(); if (!state.selectedCase) return;
      const button = event.submitter; button.disabled = true;
      state.clarificationReceipt ??= crypto.randomUUID();
      try {
        const payload = { source_message_id: state.clarificationReceipt, message: byId("clarification-message").value.trim(), return_id: byId("clarification-return").value.trim() || null };
        await apiFetch(`/api/v1/cases/${encodeURIComponent(state.selectedCase.case_id)}/messages`, { method: "POST", body: payload });
        state.clarificationReceipt = null; event.target.reset();
        await selectCase(state.selectedCase.case_id); await loadCases();
        showToast("Reply saved. Investigate again using the updated information.");
      } catch (error) { showToast(error.message, true); } finally { button.disabled = false; }
    });
  }
}

const state = { token: "", mode: "", executionMode: "unknown", openingDemo: false, cases: [], casePage: 1, casePageSize: 25, caseTotal: 0, selectedCase: null, selectedPayments: [], agentAnalysis: null, timeline: [], workflowsByIssue: {}, approvals: [], itApprovals: [], itCases: [], selectedITCase: "", itSnapshot: null, itWorkflow: null, reliability: null, selectedOperationId: "", scenarios: [], audit: [], traceId: "" };
const byId = (id) => document.getElementById(id);
const all = (selector) => Array.from(document.querySelectorAll(selector));
const escapeHtml = (value) => String(value ?? "—").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
const titleCase = (value) => value ? String(value).replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()) : "—";
const formatDate = (value) => { const date = new Date(value); return value && !Number.isNaN(date.getTime()) ? new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(date) : "—"; };
function setText(id, value) { const node = byId(id); if (node) node.textContent = value ?? "—"; }
function setStatus(id, value) { const node = byId(id); if (!node) return; node.className = `status-badge ${value || "neutral"}`; node.textContent = titleCase(value || "not_loaded"); }
function showToast(message, error = false) { const toast = byId("toast"); toast.textContent = message; toast.className = `toast show${error ? " error" : ""}`; clearTimeout(showToast.timer); showToast.timer = setTimeout(() => { toast.className = "toast"; }, 3500); }

class ApiError extends Error { constructor(message, status) { super(message); this.status = status; } }
async function apiFetch(path, options = {}) {
  const { authenticated = true, method = "GET", body = null, text = false, timeoutMs = 15000 } = options;
  if (authenticated && !state.token) throw new ApiError("Open the demo or sign in first.", 401);
  const headers = { Accept: text ? "text/plain" : "application/json" };
  if (authenticated) headers.Authorization = `Bearer ${state.token}`;
  if (body !== null) headers["Content-Type"] = "application/json";
  const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(path, { method, headers, body: body === null ? null : JSON.stringify(body), signal: controller.signal, cache: "no-store" });
    state.traceId = response.headers.get("X-ResolveOps-Trace-ID") || state.traceId;
    if (!response.ok) { let detail = `Request failed (${response.status}).`; try { detail = (await response.json()).detail || detail; } catch (_) { /* not JSON */ } throw new ApiError(detail, response.status); }
    return text ? response.text() : response.json();
  } catch (error) {
    if (error.name === "AbortError") throw new ApiError("The API request timed out.", 408);
    if (error instanceof ApiError) throw error;
    throw new ApiError("The API could not be reached.", 0);
  } finally { clearTimeout(timeout); }
}

async function checkHealth() { try { await apiFetch("/health/live", { authenticated: false, timeoutMs: 90000 }); setText("health-label", "Service healthy"); byId("health-dot").className = "ok"; } catch (_) { setText("health-label", "Service unavailable"); byId("health-dot").className = "error"; } }
function setConnected(mode) { state.mode = mode; setText("sidebar-connection", "Connected"); setText("session-label", mode === "demo" ? "Isolated sandbox session" : "Operator session"); byId("sidebar-pulse").classList.add("connected"); byId("disconnect-button").hidden = false; byId("connection-notice").classList.add("connected"); byId("overview-notice").classList.add("connected"); byId("try-demo").hidden = true; byId("reset-demo").hidden = mode !== "demo"; const live = state.executionMode === "live_model_enabled"; setStatus("inference-mode", live ? "live_multi_agent" : "rules_only"); setText("agent-mode-note", live ? "Complex customer cases run the five-role live specialist graph. One bounded run is available in each public session; simple cases and Employee IT remain deterministic." : "This workspace is using deterministic rules only; no model calls will run."); }
function disconnect() { state.token = ""; state.mode = ""; state.executionMode = "unknown"; state.cases = []; state.approvals = []; state.itApprovals = []; state.selectedCase = null; state.selectedPayments = []; state.itCases = []; state.reliability = null; setText("sidebar-connection", "Not connected"); setText("session-label", "No active session"); setStatus("inference-mode", "not_connected"); byId("sidebar-pulse").classList.remove("connected"); byId("disconnect-button").hidden = true; byId("connection-notice").classList.remove("connected"); byId("overview-notice").classList.remove("connected"); byId("try-demo").hidden = false; byId("reset-demo").hidden = true; renderCases(); renderOverview(); showToast("Session disconnected."); }

async function openDemo() {
  if (state.openingDemo || state.token) return;
  state.openingDemo = true;
  const buttons = [byId("try-demo"), byId("notice-demo"), byId("overview-demo")];
  const buttonLabels = buttons.map((button) => button.textContent);
  buttons.forEach((button) => { button.disabled = true; button.textContent = "Starting service…"; });
  setText("health-label", "Starting free demo · first visit can take about a minute");
  byId("health-dot").className = "pending";
  try {
    const session = await apiFetch("/api/v1/demo/session", { authenticated: false, method: "POST", timeoutMs: 90000 }); state.token = session.access_token; state.executionMode = session.execution_mode || "unknown"; setConnected("demo");
    setText("health-label", "Preparing isolated workspace");
    buttons.forEach((button) => { button.textContent = "Loading workspace…"; });
    state.scenarios = await apiFetch("/api/v1/demo/reset", { method: "POST" });
    await loadAll(); setText("health-label", "Service healthy"); byId("health-dot").className = "ok"; showToast("Operations workspace opened.");
  } catch (error) { state.token = ""; setText("health-label", "Demo did not load · use Retry loading"); byId("health-dot").className = "error"; showToast(error.message, true); } finally { state.openingDemo = false; buttons.forEach((button, index) => { button.disabled = false; button.textContent = buttonLabels[index]; }); }
}
async function resetDemo() { byId("reset-demo").disabled = true; try { state.scenarios = await apiFetch("/api/v1/demo/reset", { method: "POST" }); state.selectedCase = null; state.selectedITCase = ""; await loadAll(); showToast("Workspace restored to its baseline."); } catch (error) { showToast(error.message, true); } finally { byId("reset-demo").disabled = false; } }

function caseQueueQuery() { const params = new URLSearchParams({ page: String(state.casePage), page_size: String(state.casePageSize) }); const query = byId("case-search").value.trim(); const status = byId("case-filter").value; if (query) params.set("query", query); if (status) params.set("status", status); return params; }
async function loadCases() { const result = await apiFetch(`/api/v1/case-queue?${caseQueueQuery()}`); state.cases = result.items; state.caseTotal = result.total; setText("case-count", result.total); setStatus("case-list-status", "active"); setText("case-page", `Page ${result.page} · ${result.total} cases`); byId("case-prev").disabled = state.casePage <= 1; byId("case-next").disabled = state.casePage * state.casePageSize >= result.total; renderCases(); if (!state.selectedCase && state.cases.length) await selectCase(state.cases[0].case_id); }
function renderCases() { byId("case-table").innerHTML = state.cases.length ? state.cases.map((item) => `<tr data-case-id="${escapeHtml(item.case_id)}" class="${state.selectedCase?.case_id === item.case_id ? "selected" : ""}"><td><strong>${escapeHtml(item.case_id)}</strong><small>${escapeHtml(item.order_id)}</small></td><td>${escapeHtml(item.customer_name)}<small>${escapeHtml(item.customer_id)}</small></td><td>${escapeHtml(item.issue_types.map(titleCase).join(", ") || "Needs classification")}</td><td><span class="status-badge ${escapeHtml(item.status)}">${escapeHtml(titleCase(item.status))}</span></td><td>${escapeHtml(formatDate(item.updated_at))}</td></tr>`).join("") : `<tr><td colspan="5" class="table-empty">${state.token ? "No cases match the filters." : "Open the demo to load cases."}</td></tr>`; all("[data-case-id]").forEach((row) => row.addEventListener("click", () => selectCase(row.dataset.caseId))); }
async function selectCase(caseId) { try { const [customerCase, timeline] = await Promise.all([apiFetch(`/api/v1/cases/${encodeURIComponent(caseId)}`), apiFetch(`/api/v1/cases/${encodeURIComponent(caseId)}/timeline`)]); const payments = await apiFetch(`/simulator/v1/orders/${encodeURIComponent(customerCase.order_id)}/payments`); state.selectedCase = customerCase; state.selectedPayments = payments; state.agentAnalysis = null; byId("agent-summary").hidden = true; state.timeline = timeline; await loadCaseWorkflows(); renderCases(); renderCaseDetail(); renderTimeline(); renderWorkflowSummary(); loadFinalResponse(); } catch (error) { showToast(error.message, true); } }
async function loadCaseWorkflows() { state.workflowsByIssue = {}; const workflowIds = [...new Set(state.timeline.filter((event) => event.event_type === "started").map((event) => event.entity_id))]; const results = await Promise.all(workflowIds.map(async (workflowId) => { try { return await apiFetch(`/api/v1/workflows/${encodeURIComponent(workflowId)}`); } catch (_) { return null; } })); results.filter(Boolean).forEach((workflow) => { state.workflowsByIssue[workflow.issue_id] = workflow; }); }
function renderCaseJourney(item) {
  const workflows = Object.values(state.workflowsByIssue);
  const source = item.case_id.startsWith("CASE-DEMO-") ? "Seeded support example" : "Operator/API submission";
  const investigated = workflows.length > 0;
  const waiting = workflows.some((workflow) => workflow.status === "waiting_approval");
  const decided = workflows.some((workflow) => workflow.status !== "waiting_approval");
  const acted = workflows.some((workflow) => Boolean(workflow.verified_resource_id));
  const verified = item.status === "resolved" && item.issues.length > 0 && item.issues.every(issue => issue.status === "resolved");
  setText("detail-intake-source", source);
  setText("case-journey-summary", `${source}. Customer, order, payment and policy records remain inside this isolated workspace.`);
  const stages = [
    ["Complaint received", true, source],
    ["Evidence checked", investigated, investigated ? "Customer, order, payment and policy records read" : "Start Investigate to gather current records"],
    ["Decision controlled", waiting || decided, waiting ? "Waiting for a separate human decision" : decided ? "Policy and deterministic rules applied" : "Not started"],
    ["Refund tracked", acted, acted ? "Linked refund found in the payment simulator; see its current status below" : "No linked refund; some investigations need no refund"],
    ["Outcome verified", verified, verified ? "Every issue has a verified final outcome" : "Open issues still need a final outcome"],
  ];
  byId("case-journey").innerHTML = stages.map(([label, complete, detail], index) => `<li class="${complete ? "complete" : "pending"}"><b>${index + 1}</b><span><strong>${escapeHtml(label)}</strong><small>${escapeHtml(detail)}</small></span></li>`).join("");
}
function findDisplayedDuplicatePair(payments) {
  const captured = payments.filter((payment) => payment.status === "captured" && payment.captured_at);
  for (let index = 0; index < captured.length; index += 1) {
    for (let otherIndex = index + 1; otherIndex < captured.length; otherIndex += 1) {
      const first = captured[index]; const second = captured[otherIndex];
      const secondsApart = Math.abs(new Date(first.captured_at) - new Date(second.captured_at)) / 1000;
      if (first.payment_id !== second.payment_id && first.order_id === second.order_id && Number(first.amount) === Number(second.amount) && first.currency === second.currency && secondsApart <= 86400) return { first, second, secondsApart };
    }
  }
  return null;
}
function paymentEvidenceCards(item) {
  if (!item.issues.length) return [];
  const linkedIds = new Set(item.issues.flatMap((issue) => issue.payment_ids || []));
  const payments = state.selectedPayments.filter((payment) => linkedIds.size === 0 || linkedIds.has(payment.payment_id));
  if (!payments.length) return [];
  const records = payments.map((payment) => `<div class="record"><strong>Payment-provider simulator record · ${escapeHtml(payment.payment_id)}</strong><p>${escapeHtml(titleCase(payment.status))} · ${escapeHtml(payment.amount)} ${escapeHtml(payment.currency)}</p><p>Payable obligation: ${escapeHtml(payment.obligation_id || "not recorded")} · expected ${escapeHtml(payment.obligation_amount ?? "unknown")} ${escapeHtml(payment.currency)}</p><small>${escapeHtml(payment.order_id)} · captured ${escapeHtml(formatDate(payment.captured_at))}</small></div>`);
  if (!item.issues.some((issue) => issue.issue_type === "duplicate_charge")) return records;
  const match = findDisplayedDuplicatePair(payments);
  records.unshift(match ? `<div class="record payment-match"><strong>Why this is a duplicate candidate</strong><p>${escapeHtml(match.first.payment_id)} and ${escapeHtml(match.second.payment_id)} are similar captured records, ${escapeHtml(match.secondsApart.toFixed(0))} seconds apart. This similarity alone does not prove a duplicate.</p><small>The server must verify both captures cover the same payable obligation, check the order total and prior refunds, then apply current policy. Split payments or missing obligation evidence cannot authorize a refund.</small></div>` : `<div class="record payment-no-match"><strong>No similar capture pair found</strong><p>This display is a preliminary comparison, not a refund decision.</p><small>Investigation checks current records and may explain that no action is needed or request a payment specialist review.</small></div>`);
  return records;
}
function renderCaseDetail() {
  const item = state.selectedCase; if (!item) return;
  setText("detail-case-id", item.case_id); setStatus("detail-case-status", item.status); setText("detail-customer", item.customer_id); setText("detail-order", item.order_id); setText("detail-opened", formatDate(item.opened_at)); setText("detail-updated", formatDate(item.updated_at)); setText("detail-complaint", item.complaint_text || "No complaint text recorded."); renderCaseJourney(item); renderClarification();
  byId("detail-issues").innerHTML = item.issues.length ? item.issues.map((issue) => { const workflow = state.workflowsByIssue[issue.issue_id]; const waiting = workflow?.status === "waiting_approval"; const retryable = workflow?.status === "escalated"; const finished = workflow && !waiting && !retryable; const actionClass = waiting ? "review-case-approval" : finished ? "view-workflow" : "start-workflow"; const liveComplex = state.executionMode === "live_model_enabled" && item.issues.length > 1; const actionLabel = waiting ? "Review approval" : retryable ? "Retry investigation" : finished ? "View outcome" : liveComplex ? "Investigate · live agents when available" : "Investigate"; const linkedRecords = issue.issue_type === "duplicate_charge" ? `${issue.payment_ids.length} linked payment records` : issue.return_id ? `linked return ${issue.return_id}` : "no linked operational record"; return `<div class="issue-row"><strong>${escapeHtml(titleCase(issue.issue_type))}</strong><span class="status-badge ${escapeHtml(issue.status)}">${escapeHtml(titleCase(issue.status))}</span><p>${escapeHtml(issue.issue_id)} · finding: ${escapeHtml(titleCase(issue.finding))}</p><small>${escapeHtml(linkedRecords)}</small><button class="text-button ${actionClass}" data-issue-id="${escapeHtml(issue.issue_id)}" type="button">${actionLabel}</button></div>`; }).join("") : `<p class="empty-state">No supported issue classified. Review the intake summary and request clarification if needed.</p>`;
  const paymentRecords = paymentEvidenceCards(item); const persistedEvidence = item.issues.flatMap((issue) => issue.evidence.map((record) => `<div class="record"><strong>${escapeHtml(titleCase(record.source))}</strong><p>${escapeHtml(record.summary)}</p><small>${escapeHtml(record.reference_id)} · ${escapeHtml(formatDate(record.collected_at))}</small></div>`)); const workflowEvidence = item.issues.flatMap((issue) => { const workflow = state.workflowsByIssue[issue.issue_id]; if (!workflow) return []; const facts = (workflow.evidence || []).map((fact, index) => `<div class="record"><strong>Verified case fact</strong><p>${escapeHtml(fact)}</p><small>${escapeHtml(workflow.workflow_id)} · evidence ${index + 1}</small></div>`); const policies = (workflow.policy_citations || []).map((citation) => `<div class="record"><strong>${escapeHtml(citation.title)}</strong><p>${escapeHtml(citation.section)} · ${escapeHtml(citation.source)}</p><small>${escapeHtml(citation.document_id)} v${escapeHtml(citation.version)} · rank ${escapeHtml(citation.rank)}</small></div>`); return [...facts, ...policies]; }); const advisory = item.issues.map((issue) => `<div class="record"><strong>Rule-based intake</strong><p>${escapeHtml(titleCase(issue.issue_type))}</p><small>Uncalibrated rule label, not an AI confidence score · verification ${escapeHtml(titleCase(issue.verification?.status || "pending"))}</small></div>`); byId("detail-evidence").innerHTML = [...paymentRecords, ...persistedEvidence, ...workflowEvidence, ...advisory].join("") || `<p class="empty-state">No evidence recorded.</p>`;
  all(".start-workflow").forEach((button) => button.addEventListener("click", () => startIssueWorkflow(button.dataset.issueId)));
  all(".review-case-approval").forEach((button) => button.addEventListener("click", () => document.querySelector('[data-view="approvals"]').click()));
  all(".view-workflow").forEach((button) => button.addEventListener("click", () => { renderWorkflowSummary(button.dataset.issueId); byId("workflow-summary").scrollIntoView({ behavior: "smooth", block: "nearest" }); }));
}
function renderTimeline() { byId("case-timeline").innerHTML = state.timeline.length ? state.timeline.map((event) => `<div class="timeline-event"><span class="timeline-dot"></span><div><strong>${escapeHtml(titleCase(event.event_type))}</strong><p>${escapeHtml(event.entity_id)} · ${escapeHtml(event.details?.summary || event.details?.outcome || event.details?.issue_type || "Stored event")}</p><small>${escapeHtml(formatDate(event.occurred_at))}</small></div></div>`).join("") : `<p class="empty-state">No stored events.</p>`; }
function renderWorkflowSummary(issueId = "") {
  const workflow = issueId ? state.workflowsByIssue[issueId] : Object.values(state.workflowsByIssue).at(-1);
  const panel = byId("workflow-summary"); const next = byId("workflow-next-action");
  next.hidden = true; byId("agent-summary").hidden = true;
  if (!workflow) { panel.hidden = true; return; }
  panel.hidden = false; if (workflow.agent_assessment) renderAgentAnalysis(workflow.agent_assessment);
  setText("workflow-title", workflow.status === "waiting_approval" ? "Review the refund proposal" : workflow.status === "escalated" ? "Investigation needs review" : "Workflow outcome");
  setText("workflow-subtitle", `${workflow.workflow_id} · Execution: ${titleCase(workflow.execution_mode || "unknown")}`);
  setStatus("workflow-status", workflow.status);
  if (workflow.status === "waiting_approval") {
    const approval = workflow.approval;
    byId("workflow-result").innerHTML = `<div class="detail-grid"><div class="detail-item"><span>Proposed refund</span><strong>${escapeHtml(approval.amount)} ${escapeHtml(approval.currency)}</strong></div><div class="detail-item"><span>Verified payment</span><strong>${escapeHtml(approval.payment_id)}</strong></div><div class="detail-item"><span>Requested by</span><strong>${escapeHtml(approval.requested_by)}</strong></div><div class="detail-item"><span>Control</span><strong>Separate approval required</strong></div></div><p>${escapeHtml(approval.reason)}</p><p>No refund has been submitted. Review the evidence in Approvals. ${state.mode === "demo" ? "The sandbox simulates a separate approver; no real money moves." : ""}</p>`;
    next.hidden = false; return;
  }
  const citations = workflow.policy_citations || [];
  const pending = ["refund_submitted", "waiting_external"].includes(workflow.outcome);
  const verification = workflow.outcome === "refund_settled" ? "Final settlement verified" : pending ? "Submission recorded; settlement pending" : workflow.outcome === "no_action_required" ? "No refund needed" : "No completed action confirmed";
  byId("workflow-result").innerHTML = `<div class="detail-grid"><div class="detail-item"><span>Decision</span><strong>${escapeHtml(titleCase(workflow.decision))}</strong></div><div class="detail-item"><span>Outcome</span><strong>${escapeHtml(titleCase(workflow.outcome))}</strong></div><div class="detail-item"><span>Finding</span><strong>${escapeHtml(titleCase(workflow.finding))}</strong></div><div class="detail-item"><span>Verification</span><strong>${escapeHtml(verification)}</strong></div></div><p>${escapeHtml(workflow.resolution_summary)}</p><p><strong>Policy evidence:</strong> ${escapeHtml(citations.length ? citations.map((c) => `${c.document_id} v${c.version}`).join(", ") : "No supported policy citation available")}</p>${workflow.error_message ? `<p><strong>Why it stopped:</strong> ${escapeHtml(workflow.error_message)}</p><p>Add the missing information or correct source records, then retry. Previous attempts stay in the timeline.</p>` : ""}${pending && state.mode === "demo" && workflow.verified_resource_id ? `<div class="record"><strong>Synthetic payment provider</strong><p>Choose a simulated event through the settlement handler. No real money moves.</p><button type="button" class="secondary-button settlement-event" data-refund="${escapeHtml(workflow.verified_resource_id)}" data-status="completed">Simulate settlement success</button> <button type="button" class="secondary-button settlement-event" data-refund="${escapeHtml(workflow.verified_resource_id)}" data-status="failed">Simulate settlement failure</button></div>` : ""}`;
  all(".settlement-event").forEach((button) => button.addEventListener("click", () => simulateSettlement(button)));
}
function renderWorkflowProgress(issueId) { const panel = byId("workflow-summary"); panel.hidden = false; byId("workflow-next-action").hidden = true; setText("workflow-title", "Investigation running"); setText("workflow-subtitle", `${issueId} · Reading current operational records`); setStatus("workflow-status", "investigating"); byId("workflow-result").innerHTML = `<div class="detail-grid"><div class="detail-item"><span>1 · Evidence</span><strong>Customer, order and payment reads</strong></div><div class="detail-item"><span>2 · Analysis</span><strong>Specialist graph when configured</strong></div><div class="detail-item"><span>3 · Controls</span><strong>Policy and deterministic safety gates</strong></div><div class="detail-item"><span>4 · Destination</span><strong>Approval queue, safe stop or verified no-action result</strong></div></div><p>This can take longer when a live provider is enabled. The investigation cannot approve or execute a refund.</p>`; panel.scrollIntoView({ behavior: "smooth", block: "nearest" }); }
function renderWorkflowFailure(issueId, error) { const panel = byId("workflow-summary"); const contractFailure = /evidence|citation|validation/i.test(error.message); const connectionFailure = error.status === 0 || error.status === 408; panel.hidden = false; byId("workflow-next-action").hidden = true; setText("workflow-title", connectionFailure ? "Investigation status needs refresh" : "Investigation stopped safely"); setText("workflow-subtitle", `${issueId} · ${connectionFailure ? "Browser did not receive a final status" : "No approval created"}`); setStatus("workflow-status", connectionFailure ? "unknown" : "escalated"); byId("workflow-result").innerHTML = `<div class="detail-grid"><div class="detail-item"><span>Investigation result</span><strong>${escapeHtml(connectionFailure ? "Connection lost" : contractFailure ? "Validation failed" : "Request failed")}</strong></div><div class="detail-item"><span>Approval</span><strong>${escapeHtml(connectionFailure ? "Not confirmed" : "Blocked")}</strong></div><div class="detail-item"><span>Sensitive action</span><strong>${escapeHtml(connectionFailure ? "No completion shown" : "Not executed")}</strong></div><div class="detail-item"><span>Required next step</span><strong>${escapeHtml(connectionFailure ? "Refresh this case and audit history" : contractFailure ? "Complete evidence and policy citations" : "Review the recorded error, then retry")}</strong></div></div><p>${escapeHtml(connectionFailure ? "The browser timed out before receiving the workflow result. Refresh the case to reconcile persisted state before retrying." : contractFailure ? "The multi-agent investigation did not meet the evidence contract. ResolveOps stopped before approval or execution." : "ResolveOps did not create an approval from this failed request. Review the error and retry only after correcting its cause.")}</p><p><strong>Safe stop:</strong> ${escapeHtml(error.message)}</p>`; panel.scrollIntoView({ behavior: "smooth", block: "nearest" }); }
function loadFinalResponse() { const panel = byId("final-response"); const workflow = Object.values(state.workflowsByIssue).filter((item) => item.final_response).at(-1); if (!workflow) { panel.hidden = true; return; } setText("final-response-text", workflow.final_response.message); panel.hidden = false; }
async function startIssueWorkflow(issueId) {
  const issue = state.selectedCase?.issues.find((candidate) => candidate.issue_id === issueId);
  if (!issue) return;
  state.investigationRequests ??= {};
  const workflowId = state.investigationRequests[issueId] || `WF-${crypto.randomUUID()}`;
  state.investigationRequests[issueId] = workflowId;
  const button = document.querySelector(`.start-workflow[data-issue-id="${CSS.escape(issueId)}"]`);
  if (button) { button.disabled = true; button.textContent = "Investigating…"; }
  renderWorkflowProgress(issueId);
  try {
    const result = await apiFetch("/api/v1/workflows", { method: "POST", timeoutMs: 100000,
      body: { workflow_id: workflowId, case_id: state.selectedCase.case_id, issue_id: issueId } });
    delete state.investigationRequests[issueId];
    await Promise.all([loadApprovals(), loadCases(), selectCase(state.selectedCase.case_id), loadAudit()]);
    renderWorkflowSummary(issueId);
    showToast(result.status === "waiting_approval" ? "Proposal ready. Review before any refund is submitted." : `Investigation finished: ${titleCase(result.outcome)}.`);
  } catch (error) {
    // Reuse this ID after a lost response so retry reconciles the original execution.
    renderWorkflowFailure(issueId, error); showToast(error.message, true);
  } finally { if (button?.isConnected) { button.disabled = false; button.textContent = "Investigate"; } }
}
function renderAgentAnalysis(result) {
  if (!result) return;
  byId("agent-summary").hidden = false;
  setStatus("agent-summary-status", result.status);
  const usage = result.usage || {};
  const tokens = usage.input_tokens == null || usage.output_tokens == null
    ? "unknown tokens" : `${usage.input_tokens + usage.output_tokens} tokens`;
  setText("agent-summary-subtitle", `${result.workflow_id} · ${result.agent_call_count} model calls · ${result.tool_call_count} tools · ${tokens}`);
  const skipped = ["Not run after a safety stop", "skipped"];
  const roles = [
    ["Supervisor", result.supervisor?.goal || skipped[0], result.supervisor?.next_agent || skipped[1]],
    ["Investigator", result.investigation ? `${result.investigation.evidence_ids.length} grounded evidence items` : skipped[0], result.investigation ? (result.investigation.complete ? "complete" : "stopped") : skipped[1]],
    ["Policy", result.policy?.policy_interpretation || skipped[0], result.policy ? (result.policy.missing_policy ? "missing policy" : `${result.policy.citations.length} citations`) : skipped[1]],
    ["Resolution", result.resolution?.issue_resolutions.map(item => item.recommendation).join(" ") || skipped[0], result.resolution ? (result.resolution.escalation_needed ? "escalate" : "proposed") : skipped[1]],
    ["Independent review", result.critic?.summary || skipped[0], result.critic?.decision || skipped[1]]
  ];
  const cost = usage.estimated_cost_usd == null ? "Unknown" : `$${Number(usage.estimated_cost_usd).toFixed(6)}`;
  byId("agent-summary-result").innerHTML = `<div class="detail-grid"><div class="detail-item"><span>Model calls</span><strong>${escapeHtml(result.agent_call_count)}</strong></div><div class="detail-item"><span>Tool reads</span><strong>${escapeHtml(result.tool_call_count)}</strong></div><div class="detail-item"><span>Tokens</span><strong>${escapeHtml((usage.input_tokens || 0) + (usage.output_tokens || 0))}</strong></div><div class="detail-item"><span>Estimated cost</span><strong>${escapeHtml(cost)}</strong></div></div><div class="record-list">${roles.map(([role, summary, outcome]) => `<div class="record"><strong>${escapeHtml(role)}</strong><p>${escapeHtml(summary)}</p><small>Outcome: ${escapeHtml(titleCase(outcome))}</small></div>`).join("")}</div>${result.stop_reason ? `<p>Stopped: ${escapeHtml(result.stop_reason)}</p>` : ""}<p><strong>Trace:</strong> ${escapeHtml((result.agent_run_ids || []).join(", "))}</p><p><strong>Authority boundary:</strong> Agents can recommend. Policy rules, human approval, typed actions and fresh-state checks control every sensitive change.</p>`;
}
async function submitComplaint(event) {
  event.preventDefault(); const button = event.submitter; button.disabled = true;
  state.complaintReceipt ??= crypto.randomUUID();
  try {
    const created = await apiFetch("/api/v1/cases", { method: "POST", body: {
      customer_id: byId("complaint-customer").value.trim(), order_id: byId("complaint-order").value.trim(),
      complaint: byId("complaint-text").value.trim(), source_message_id: state.complaintReceipt } });
    state.complaintReceipt = null; closeCaseDrawer(); state.casePage = 1;
    await loadCases(); await selectCase(created.case_id); showToast(`Complaint received · ${created.case_id}`);
  } catch (error) { showToast(error.message, true); } finally { button.disabled = false; }
}
async function submitFeedback(event) { event.preventDefault(); if (!state.selectedCase) return; const firstIssue = state.selectedCase.issues[0]; try { await apiFetch("/api/v1/feedback", { method: "POST", body: { case_id: state.selectedCase.case_id, kind: byId("feedback-kind").value, original_value: { issue_type: firstIssue?.issue_type || null }, corrected_value: { correction: byId("feedback-correction").value.trim() }, reason: byId("feedback-reason").value.trim() } }); event.target.reset(); showToast("Correction saved for human review."); } catch (error) { showToast(error.message, true); } }

async function loadApprovals() { [state.approvals, state.itApprovals] = await Promise.all([apiFetch("/api/v1/approvals"), apiFetch("/api/v1/it/approvals")]); const pending = state.approvals.filter((item) => item.status === "pending").length + state.itApprovals.filter((item) => item.status === "pending").length; setText("approval-count", pending); renderApprovals(); }
function renderApprovals() { const refundCards = state.approvals.map((item) => `<article class="approval-card"><div class="pane-heading"><div><h2>${escapeHtml(item.approval_id)}</h2><span>${escapeHtml(item.case_id)} · ${escapeHtml(item.issue_id)}</span></div><span class="status-badge ${escapeHtml(item.status)}">${escapeHtml(titleCase(item.status))}</span></div><div class="detail-grid"><div class="detail-item"><span>Action</span><strong>Issue refund</strong></div><div class="detail-item"><span>Amount</span><strong>${escapeHtml(item.amount)} ${escapeHtml(item.currency)}</strong></div><div class="detail-item"><span>Payment</span><strong>${escapeHtml(item.payment_id)}</strong></div><div class="detail-item"><span>Requested</span><strong>${escapeHtml(formatDate(item.requested_at))}</strong></div></div><p>${escapeHtml(item.reason)}</p>${item.status === "pending" ? `<div class="approval-actions"><input aria-label="Decision note" data-note-for="${escapeHtml(item.approval_id)}" placeholder="Decision reason"><button class="primary-button approval-decision" data-approval-id="${escapeHtml(item.approval_id)}" data-decision="approve" type="button">Approve</button><button class="secondary-button approval-decision" data-approval-id="${escapeHtml(item.approval_id)}" data-decision="reject" type="button">Reject</button></div>` : `<p>Decision: ${escapeHtml(item.decision_note || "No note")}</p>`}</article>`); const itCards = state.itApprovals.map((item) => `<article class="approval-card"><div class="pane-heading"><div><h2>${escapeHtml(item.approval_id)}</h2><span>${escapeHtml(item.case_id)} · ${escapeHtml(item.access_request_id)}</span></div><span class="status-badge ${escapeHtml(item.status)}">${escapeHtml(titleCase(item.status))}</span></div><div class="detail-grid"><div class="detail-item"><span>Action</span><strong>Grant repository access</strong></div><div class="detail-item"><span>Employee</span><strong>${escapeHtml(item.employee_name)}</strong></div><div class="detail-item"><span>Repository</span><strong>${escapeHtml(item.repository_name)} · ${escapeHtml(titleCase(item.requested_level))}</strong></div><div class="detail-item"><span>Manager</span><strong>${escapeHtml(item.manager_employee_id)}</strong></div></div><p>Confirm the manager-approved business need before granting access.</p>${item.status === "pending" ? `<div class="approval-actions"><input aria-label="IT decision note" data-it-note-for="${escapeHtml(item.case_id)}" placeholder="Decision reason"><button class="primary-button it-approval-decision" data-case-id="${escapeHtml(item.case_id)}" data-decision="approve" type="button">Approve access</button><button class="secondary-button it-approval-decision" data-case-id="${escapeHtml(item.case_id)}" data-decision="reject" type="button">Reject</button></div>` : `<p>Decision: ${escapeHtml(item.decision_note || "No note")}</p>`}</article>`); const cards = [...refundCards, ...itCards]; byId("approval-list").innerHTML = cards.length ? cards.join("") : `<p class="empty-state">No approval requests recorded.</p>`; all(".approval-decision").forEach((button) => button.addEventListener("click", () => decideApproval(button.dataset.approvalId, button.dataset.decision))); all(".it-approval-decision").forEach((button) => button.addEventListener("click", () => decideITApproval(button.dataset.caseId, button.dataset.decision))); }
async function decideApproval(approvalId, decision) {
  const note = document.querySelector(`[data-note-for="${CSS.escape(approvalId)}"]`).value.trim();
  if (!note) { showToast("Enter a decision reason.", true); return; }
  const approval = state.approvals.find((item) => item.approval_id === approvalId);
  try {
    const result = await apiFetch(`/api/v1/approvals/${encodeURIComponent(approvalId)}/decision`, { method: "POST", body: { decision, note }, timeoutMs: 100000 });
    await Promise.all([loadApprovals(), loadReliability(), loadAudit(), loadCases()]);
    navigateToView("cases"); if (approval) await selectCase(approval.case_id);
    showToast(result.outcome === "refund_submitted" ? "Refund submitted. Settlement is still pending." : result.outcome === "refund_settled" ? "Refund settlement verified." : result.error_message || `Decision recorded: ${titleCase(result.outcome)}.`, result.outcome === "needs_review" && decision === "approve");
  } catch (error) { showToast(error.message, true); }
}
async function decideITApproval(caseId, decision) { const note = document.querySelector(`[data-it-note-for="${CSS.escape(caseId)}"]`).value.trim(); if (!note) { showToast("Enter a decision reason.", true); return; } try { await apiFetch(`/api/v1/it/approvals/${encodeURIComponent(caseId)}/decision`, { method: "POST", body: { decision, note } }); await Promise.all([loadApprovals(), loadITQueue(), loadAudit()]); document.querySelector('[data-view="it"]').click(); await selectITCase(caseId); showToast(decision === "approve" ? "Access approved. You can process the request now." : "Access request rejected."); } catch (error) { showToast(error.message, true); } }

async function loadITQueue() { const result = await apiFetch("/api/v1/it/cases?page_size=100"); state.itCases = result.items; setText("it-count", result.total); renderITQueue(); if (!state.selectedITCase && state.itCases.length) await selectITCase(state.itCases[0].case_id); }
function renderITQueue() { byId("it-case-table").innerHTML = state.itCases.length ? state.itCases.map((item) => `<tr data-it-case="${escapeHtml(item.case_id)}" class="${item.case_id === state.selectedITCase ? "selected" : ""}"><td><strong>${escapeHtml(item.case_id)}</strong><small>${escapeHtml(item.request_id)}</small></td><td>${escapeHtml(item.employee_name)}<small>${escapeHtml(item.employee_id)}</small></td><td><span class="status-badge ${escapeHtml(item.request_status)}">${escapeHtml(titleCase(item.request_status))}</span></td><td>${escapeHtml(formatDate(item.updated_at))}</td></tr>`).join("") : `<tr><td colspan="4" class="table-empty">No IT requests recorded.</td></tr>`; all("[data-it-case]").forEach((row) => row.addEventListener("click", () => selectITCase(row.dataset.itCase))); }
async function selectITCase(caseId) {
  try {
    state.selectedITCase = caseId;
    const workflowRequest = apiFetch(`/api/v1/it/cases/${encodeURIComponent(caseId)}/workflow`).catch((error) => { if (error.status === 404) return null; throw error; });
    [state.itSnapshot, state.itWorkflow] = await Promise.all([apiFetch(`/simulator/v1/it/cases/${encodeURIComponent(caseId)}`), workflowRequest]);
    renderITQueue(); renderITDetail(state.itSnapshot); if (state.itWorkflow) renderITResult(state.itWorkflow);
    if (window.loadITAttemptHistory) await window.loadITAttemptHistory(caseId);
  } catch (error) { showToast(error.message, true); }
}
function renderITDetail(data) { const approval = state.itApprovals.find((item) => item.case_id === data.access_case.case_id); const pending = data.access_request.status === "pending_approval"; const rejected = data.access_request.status === "rejected"; const fulfilled = Boolean(data.repository_access); setText("it-employee-name", data.employee.name); setStatus("it-employment", data.employee.status); setText("it-case-id", data.access_case.case_id); setStatus("it-status", data.access_case.status); setText("it-step-request", `${titleCase(data.access_request.status)} · ${titleCase(data.access_request.requested_level)}`); setText("it-step-identity", `${titleCase(data.identity.status)} · MFA ${data.identity.mfa_enrolled ? "enrolled" : "missing"}`); setText("it-step-approval", data.access_request.approved_by ? `Approved by ${data.access_request.approved_by}` : rejected ? "Rejected" : "Approval pending"); setText("it-step-group", data.group_membership ? `${titleCase(data.group_membership.status)} membership` : "Not granted"); setText("it-step-grant", data.repository_access ? `${titleCase(data.repository_access.status)} ${titleCase(data.repository_access.level)}` : "Not granted"); setText("it-step-notification", `${titleCase(data.ticket.status)} · ${data.notifications.length ? "notice sent" : "no notice"}`); byId("it-identity").innerHTML = [["Employee", data.employee.employee_id], ["Employment", titleCase(data.employee.status)], ["Identity", data.identity.username], ["MFA", data.identity.mfa_enrolled ? "Enrolled" : "Missing"], ["Team", data.team.name], ["Git account", data.git_account.username], ["Repository", data.repository.name], ["Requested level", titleCase(data.access_request.requested_level)]].map(([label, value]) => `<div class="detail-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join(""); const approvalRecord = approval ? `<div class="record"><strong>${escapeHtml(approval.approval_id)}</strong><p>${escapeHtml(approval.decision_note || "Waiting for a recorded human decision.")}</p><small>${escapeHtml(titleCase(approval.status))}${approval.decided_by ? ` · ${escapeHtml(approval.decided_by)}` : ""}</small></div>` : ""; const notificationRecords = data.notifications.map((item) => `<div class="record"><strong>${escapeHtml(item.notification_id)}</strong><p>${escapeHtml(item.message)}</p><small>${escapeHtml(titleCase(item.status))} · ${escapeHtml(formatDate(item.sent_at))}</small></div>`).join(""); byId("it-records").innerHTML = `<div class="record"><strong>${escapeHtml(data.access_request.access_request_id)}</strong><p>${escapeHtml(data.access_request.justification)}</p><small>${escapeHtml(titleCase(data.access_request.status))}</small></div>${approvalRecord}<div class="record"><strong>${escapeHtml(data.ticket.ticket_id)}</strong><p>${escapeHtml(data.ticket.subject)}</p><small>${escapeHtml(titleCase(data.ticket.status))}</small></div>${notificationRecords}`; byId("review-it-approval").hidden = !pending; byId("run-it-workflow").disabled = pending || rejected || fulfilled; byId("run-it-workflow").textContent = pending ? "Approval required" : rejected ? "Request rejected" : fulfilled ? "Access verified" : "Run safety checks and process"; if (fulfilled) renderPersistedITResult(data); else { setText("it-result-title", pending ? "Manager approval required" : rejected ? "Request rejected" : "Ready for controlled processing"); setStatus("it-result-status", pending ? "pending" : rejected ? "rejected" : "not_started"); byId("it-result").innerHTML = pending ? "Review the human approval, record a reason, then return here to process the grant." : rejected ? "The request was rejected. No directory membership or repository access was created." : "The workflow will verify employment, identity, MFA, team membership, approval, current access, and policy before making any change."; } }
async function runITWorkflow() { if (!state.selectedITCase) return; const button = byId("run-it-workflow"); button.disabled = true; try { const result = await apiFetch(`/api/v1/it/cases/${encodeURIComponent(state.selectedITCase)}/execute`, { method: "POST" }); await Promise.all([selectITCase(state.selectedITCase), loadITQueue(), loadReliability(), loadAudit()]); renderITResult(result); showToast(result.outcome === "access_verified" ? "Repository access granted and verified." : result.outcome === "needs_review" ? "Safety checks stopped the request for manual review." : "Existing access verified; no duplicate grant was created."); } catch (error) { button.disabled = false; showToast(error.message, true); } }
function renderITResult(result) { setText("it-result-title", result.workflow_id); setStatus("it-result-status", result.status); byId("it-result").innerHTML = `<div class="detail-grid"><div class="detail-item"><span>Outcome</span><strong>${escapeHtml(titleCase(result.outcome))}</strong></div><div class="detail-item"><span>Decision</span><strong>${escapeHtml(titleCase(result.decision))}</strong></div><div class="detail-item"><span>Verified access</span><strong>${escapeHtml(result.verified_access_id || "No new access")}</strong></div><div class="detail-item"><span>Policy citations</span><strong>${escapeHtml((result.policy_citations || []).length)}</strong></div></div><p>${escapeHtml(result.resolution_summary)}</p>${result.error_message ? `<p><strong>Safety stop:</strong> ${escapeHtml(result.error_message)}</p>` : ""}<p><strong>Workflow path:</strong> ${escapeHtml(result.node_history.map(titleCase).join(" → "))}</p>`; }
function renderPersistedITResult(data) { setText("it-result-title", "Persisted verified state"); setStatus("it-result-status", data.access_case.status); byId("it-result").innerHTML = `<div class="detail-grid"><div class="detail-item"><span>Access ID</span><strong>${escapeHtml(data.repository_access.access_id)}</strong></div><div class="detail-item"><span>Level</span><strong>${escapeHtml(titleCase(data.repository_access.level))}</strong></div><div class="detail-item"><span>Directory group</span><strong>${escapeHtml(data.group_membership ? titleCase(data.group_membership.status) : "Missing")}</strong></div><div class="detail-item"><span>Ticket</span><strong>${escapeHtml(titleCase(data.ticket.status))}</strong></div><div class="detail-item"><span>Notification</span><strong>${escapeHtml(data.notifications.length ? "Sent" : "None")}</strong></div><div class="detail-item"><span>Fresh read</span><strong>Matched authorized request</strong></div></div><p>Persisted identity, directory membership, repository access, ticket, and notification state all confirm completion.</p>`; }

function metricValue(text, name) { return text.split("\n").filter((line) => line.startsWith(name) && !line.startsWith("#")).reduce((sum, line) => sum + (Number(line.trim().split(/\s+/).at(-1)) || 0), 0); }
async function loadMetrics() { try { const text = await apiFetch("/metrics", { text: true }); setText("metric-requests", metricValue(text, "resolveops_http_requests_total")); setText("metric-rejections", metricValue(text, "resolveops_http_rejections_total")); setText("metrics-status", "Active"); setText("reliability-trace", state.traceId || "—"); } catch (_) { setText("metrics-status", "Not loaded"); } }
function formatMilliseconds(value) { return value === null || value === undefined ? "No samples" : `${Number(value).toFixed(value >= 100 ? 0 : 1)} ms`; }
async function loadReliability() { state.reliability = await apiFetch("/api/v1/reliability/summary"); renderReliability(); setStatus("reliability-status", "active"); }
function renderReliability() { const summary = state.reliability; if (!summary) return; setText("reliability-total", summary.total_operations); setText("reliability-p50", formatMilliseconds(summary.p50_latency_ms)); setText("reliability-p95", formatMilliseconds(summary.p95_latency_ms)); setText("reliability-failures", summary.failed_operation_count); setText("reliability-retries", summary.retry_scheduled_count); setText("reliability-waits", summary.wait_scheduled_count); setText("reliability-recoveries", summary.recovery_event_count); setText("reliability-reviews", summary.manual_review_count); const operations = summary.recent_operations; if (!operations.some((item) => item.operation_id === state.selectedOperationId)) state.selectedOperationId = operations[0]?.operation_id || ""; byId("reliability-operations").innerHTML = operations.length ? operations.map((item) => `<button class="record reliability-operation ${item.operation_id === state.selectedOperationId ? "selected" : ""}" data-operation-id="${escapeHtml(item.operation_id)}" type="button"><span class="record-head"><strong>${escapeHtml(item.operation_id)}</strong><span class="status-badge ${escapeHtml(item.status)}">${escapeHtml(titleCase(item.status))}</span></span><span class="record-meta"><span>${escapeHtml(titleCase(item.operation_type))}</span><span>${escapeHtml(formatMilliseconds(item.duration_ms))}</span><span>${escapeHtml(item.events.length)} events</span></span></button>`).join("") : `<p class="empty-state">No operations recorded.</p>`; all(".reliability-operation").forEach((button) => button.addEventListener("click", () => { state.selectedOperationId = button.dataset.operationId; renderReliability(); })); const selected = operations.find((item) => item.operation_id === state.selectedOperationId); setText("reliability-operation-id", selected?.operation_id || "Choose an operation"); byId("reliability-events").innerHTML = selected?.events.length ? selected.events.map((event) => `<div class="timeline-event"><span class="timeline-dot"></span><div><strong>${escapeHtml(titleCase(event.event_type))}</strong><p>Attempt ${escapeHtml(event.attempt_number || "—")} · ${escapeHtml(event.details?.reason || event.details?.error_code || event.details?.disposition || "Stored execution event")}</p><small>${escapeHtml(formatDate(event.occurred_at))}</small></div></div>`).join("") : `<p class="empty-state">${selected ? "No retry or recovery events were needed." : "Select an operation."}</p>`; }

async function loadAudit() { const caseId = byId("audit-case-filter").value.trim(); const suffix = caseId ? `?case_id=${encodeURIComponent(caseId)}` : ""; state.audit = await apiFetch(`/api/v1/audit/events${suffix}`); setText("audit-case-id", caseId || "All cases"); byId("audit-events").innerHTML = state.audit.length ? state.audit.map((item) => `<tr><td>${escapeHtml(formatDate(item.occurred_at))}</td><td>${escapeHtml(item.actor_id)}</td><td>${escapeHtml(item.case_id)}</td><td class="mono">${escapeHtml(item.workflow_or_operation_id)}</td><td>${escapeHtml(titleCase(item.event_type))}</td><td>${escapeHtml(titleCase(item.result))}</td></tr>`).join("") : `<tr><td colspan="6" class="table-empty">No matching audit events.</td></tr>`; }
async function loadScenarios() { if (state.mode !== "demo") return; state.scenarios = await apiFetch("/api/v1/demo/scenarios"); byId("scenario-select").innerHTML = `<option value="">Demo scenarios</option>${state.scenarios.map((item) => `<option value="${escapeHtml(item.case_id)}">${escapeHtml(item.scenario_id)} · ${escapeHtml(item.title)}</option>`).join("")}`; }

function renderOverview() {
  const connected = Boolean(state.token);
  const pendingRefunds = state.approvals.filter((item) => item.status === "pending");
  const pendingAccess = state.itApprovals.filter((item) => item.status === "pending");
  const escalatedCases = state.cases.filter((item) => item.status === "escalated");
  const operationCount = state.reliability?.total_operations ?? 0;
  const failedOperations = state.reliability?.failed_operation_count ?? 0;
  const pendingCount = pendingRefunds.length + pendingAccess.length;

  setText("overview-cases", connected ? state.caseTotal : "—");
  setText("overview-cases-note", connected ? `${escalatedCases.length} need review` : "Awaiting workspace");
  setText("overview-approvals", connected ? pendingCount : "—");
  setText("overview-it", connected ? state.itCases.length : "—");
  setText("overview-operations", connected ? operationCount : "—");
  setText(
    "overview-reliability-note",
    connected ? `${failedOperations} failed · ${state.reliability?.recovery_event_count ?? 0} recovered` : "Execution history",
  );
  setText("overview-updated", connected ? `Updated ${formatDate(new Date().toISOString())}` : "Not connected");

  const attention = [
    ...pendingRefunds.map((item) => ({
      kind: "approval",
      title: `Refund approval · ${item.case_id}`,
      detail: `${item.amount} ${item.currency} · ${item.issue_id}`,
      status: "pending",
    })),
    ...pendingAccess.map((item) => ({
      kind: "approval",
      title: `Access approval · ${item.case_id}`,
      detail: `${item.employee_name} · ${item.repository_name}`,
      status: "pending",
    })),
    ...escalatedCases.map((item) => ({
      kind: "case",
      caseId: item.case_id,
      title: `Evidence review · ${item.case_id}`,
      detail: `${item.customer_name} · ${item.issue_types.map(titleCase).join(", ")}`,
      status: "escalated",
    })),
  ];

  setStatus("overview-attention-status", connected ? (attention.length ? "active" : "completed") : "not_loaded");
  byId("overview-attention").innerHTML = attention.length
    ? attention.map((item) => `<button class="record attention-link" data-attention-kind="${escapeHtml(item.kind)}" data-attention-case="${escapeHtml(item.caseId || "")}" type="button"><span class="record-head"><strong>${escapeHtml(item.title)}</strong><span class="status-badge ${escapeHtml(item.status)}">${escapeHtml(titleCase(item.status))}</span></span><p>${escapeHtml(item.detail)}</p></button>`).join("")
    : `<p class="empty-state">${connected ? "No work currently requires approval or manual review." : "Open the workspace to load operational work."}</p>`;
  all("[data-attention-kind]").forEach((button) => button.addEventListener("click", async () => {
    if (button.dataset.attentionKind === "approval") {
      document.querySelector('[data-view="approvals"]').click();
      return;
    }
    document.querySelector('[data-view="cases"]').click();
    if (button.dataset.attentionCase) await selectCase(button.dataset.attentionCase);
  }));
}
async function loadAll() { try { await Promise.all([loadApprovals(), loadCases(), loadITQueue(), loadMetrics(), loadReliability(), loadScenarios(), loadAudit()]); setText("last-updated", `Updated ${formatDate(new Date().toISOString())}`); renderOverview(); } catch (error) { if (error.status === 401) disconnect(); showToast(error.message, true); } }

function openCaseDrawer() { byId("case-drawer").hidden = false; byId("complaint-text").focus(); }
function closeCaseDrawer() { byId("case-drawer").hidden = true; }
function openDialog() { byId("connect-dialog").hidden = false; byId("api-key").focus(); }
function closeDialog() { byId("connect-dialog").hidden = true; byId("connect-error").hidden = true; }
async function secureSignIn(event) { event.preventDefault(); const token = byId("api-key").value.trim(); if (!token) return; state.token = token; try { await apiFetch("/api/v1/cases"); setConnected("operator"); byId("api-key").value = ""; closeDialog(); await loadAll(); } catch (error) { state.token = ""; byId("connect-error").textContent = error.message; byId("connect-error").hidden = false; } }

function navigateToView(viewName) { const button = document.querySelector(`.nav-item[data-view="${CSS.escape(viewName)}"]`); if (!button) return; all(".nav-item").forEach((item) => item.classList.toggle("active", item === button)); all(".view").forEach((view) => view.classList.toggle("active", view.dataset.viewPanel === viewName)); document.querySelector(".sidebar").classList.remove("open"); }
all(".nav-item").forEach((button) => button.addEventListener("click", () => navigateToView(button.dataset.view)));
all(".refresh-button").forEach((button) => button.addEventListener("click", () => state.token ? loadAll() : showToast("Open the workspace or sign in first.", true)));
byId("try-demo").addEventListener("click", openDemo); byId("notice-demo").addEventListener("click", openDemo); byId("overview-demo").addEventListener("click", openDemo); byId("open-customer-workflow").addEventListener("click", () => navigateToView("cases")); byId("open-employee-workflow").addEventListener("click", () => navigateToView("it")); byId("reset-demo").addEventListener("click", resetDemo); byId("open-connect").addEventListener("click", openDialog); byId("close-connect").addEventListener("click", closeDialog); byId("connect-form").addEventListener("submit", secureSignIn); byId("disconnect-button").addEventListener("click", disconnect); byId("new-case-button").addEventListener("click", openCaseDrawer); byId("close-case-drawer").addEventListener("click", closeCaseDrawer); byId("cancel-case").addEventListener("click", closeCaseDrawer); byId("complaint-form").addEventListener("submit", submitComplaint); byId("feedback-form").addEventListener("submit", submitFeedback); byId("workflow-next-action").addEventListener("click", () => navigateToView("approvals"));
let caseSearchTimer; byId("case-search").addEventListener("input", () => { clearTimeout(caseSearchTimer); caseSearchTimer = setTimeout(() => { state.casePage = 1; if (state.token) loadCases(); }, 250); }); byId("case-filter").addEventListener("change", () => { state.casePage = 1; if (state.token) loadCases(); }); byId("case-prev").addEventListener("click", () => { state.casePage -= 1; loadCases(); }); byId("case-next").addEventListener("click", () => { state.casePage += 1; loadCases(); }); byId("audit-filter-button").addEventListener("click", () => state.token && loadAudit()); byId("scenario-select").addEventListener("change", (event) => { const scenario = state.scenarios.find((item) => item.case_id === event.target.value); if (!scenario) return; if (scenario.domain === "employee_it") { navigateToView("it"); selectITCase(scenario.case_id); } else { navigateToView("cases"); selectCase(scenario.case_id); } }); byId("mobile-menu").addEventListener("click", () => document.querySelector(".sidebar").classList.toggle("open")); byId("toggle-key").addEventListener("click", () => { const input = byId("api-key"); input.type = input.type === "password" ? "text" : "password"; byId("toggle-key").textContent = input.type === "password" ? "Show" : "Hide"; }); byId("run-it-workflow").addEventListener("click", runITWorkflow); byId("review-it-approval").addEventListener("click", () => navigateToView("approvals")); byId("theme-toggle").addEventListener("click", () => { const dark = document.documentElement.dataset.theme === "dark"; document.documentElement.dataset.theme = dark ? "" : "dark"; byId("theme-toggle").textContent = dark ? "Dark mode" : "Light mode"; }); window.addEventListener("keydown", (event) => { if (event.key === "Escape") { closeDialog(); closeCaseDrawer(); } }); renderOverview(); openDemo();
