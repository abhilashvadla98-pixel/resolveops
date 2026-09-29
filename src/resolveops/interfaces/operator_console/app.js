"use strict";

const state = { token: "", mode: "", cases: [], selectedCase: null, timeline: [], approvals: [], traceId: "" };
const byId = (id) => document.getElementById(id);
const all = (selector) => Array.from(document.querySelectorAll(selector));
const escapeHtml = (value) => String(value ?? "—").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);

function titleCase(value) { return value ? String(value).replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()) : "—"; }
function formatDate(value) { const date = new Date(value); return value && !Number.isNaN(date.getTime()) ? new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(date) : "—"; }
function setText(id, value) { const node = byId(id); if (node) node.textContent = value ?? "—"; }
function setStatus(id, value) { const node = byId(id); if (!node) return; const known = ["open", "in_progress", "pending_approval", "pending", "approved", "resolved", "fulfilled", "escalated", "failed", "active"]; node.className = `status-badge ${known.includes(value) ? value : "neutral"}`; node.textContent = titleCase(value || "not loaded"); }
function showToast(message, error = false) { const toast = byId("toast"); toast.textContent = message; toast.className = `toast show${error ? " error" : ""}`; clearTimeout(showToast.timer); showToast.timer = setTimeout(() => { toast.className = "toast"; }, 3500); }

class ApiError extends Error { constructor(message, status) { super(message); this.status = status; } }

async function apiFetch(path, options = {}) {
  const { authenticated = true, method = "GET", body = null, text = false } = options;
  if (authenticated && !state.token) throw new ApiError("Open the demo or sign in first.", 401);
  const headers = { Accept: text ? "text/plain" : "application/json" };
  if (authenticated) headers.Authorization = `Bearer ${state.token}`;
  if (body !== null) headers["Content-Type"] = "application/json";
  const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 12000);
  try {
    const response = await fetch(path, { method, headers, body: body === null ? null : JSON.stringify(body), signal: controller.signal, cache: "no-store" });
    state.traceId = response.headers.get("X-ResolveOps-Trace-ID") || state.traceId;
    if (!response.ok) { let detail = `Request failed (${response.status}).`; try { detail = (await response.json()).detail || detail; } catch (_) { /* response was not JSON */ } throw new ApiError(detail, response.status); }
    return text ? response.text() : response.json();
  } catch (error) {
    if (error.name === "AbortError") throw new ApiError("The API request timed out.", 408);
    if (error instanceof ApiError) throw error;
    throw new ApiError("The API could not be reached.", 0);
  } finally { clearTimeout(timeout); }
}

async function checkHealth() {
  try { await apiFetch("/health/live", { authenticated: false }); setText("health-label", "API online"); byId("health-dot").className = "ok"; }
  catch (_) { setText("health-label", "API unavailable"); byId("health-dot").className = "error"; }
}

function setConnected(mode) {
  state.mode = mode; setText("sidebar-connection", "Connected"); setText("session-label", mode === "demo" ? "Restricted demo session" : "Operator session");
  byId("sidebar-pulse").classList.add("connected"); byId("disconnect-button").hidden = false; byId("connection-notice").classList.add("connected");
  byId("connection-notice").querySelector("strong").textContent = "Synthetic workspace connected";
  byId("connection-notice").querySelector("p").textContent = "Cases, approvals, IT state, and telemetry are loaded from authenticated APIs.";
  byId("notice-demo").hidden = true; setText("last-updated", `Updated ${formatDate(new Date().toISOString())}`);
}

function disconnect() {
  state.token = ""; state.mode = ""; state.cases = []; state.selectedCase = null; state.timeline = []; state.approvals = [];
  setText("sidebar-connection", "Not connected"); setText("session-label", "No active session"); byId("sidebar-pulse").classList.remove("connected"); byId("disconnect-button").hidden = true; byId("notice-demo").hidden = false;
  byId("connection-notice").classList.remove("connected"); renderCases(); renderApprovals(); showToast("Session disconnected.");
}

async function openDemo() {
  const buttons = [byId("try-demo"), byId("notice-demo")]; buttons.forEach((button) => { button.disabled = true; });
  try { const session = await apiFetch("/api/v1/demo/session", { authenticated: false, method: "POST" }); state.token = session.access_token; setConnected("demo"); await loadAll(); showToast("Demo workspace opened."); }
  catch (error) { showToast(error.message === "demo is not enabled" ? "Demo mode is not enabled on this server. Use secure sign in." : error.message, true); }
  finally { buttons.forEach((button) => { button.disabled = false; }); }
}

async function loadCases() {
  state.cases = await apiFetch("/api/v1/cases"); setText("case-count", state.cases.length); setStatus("case-list-status", "active"); renderCases();
  if (!state.selectedCase && state.cases.length) await selectCase(state.cases[0].case_id);
}

function filteredCases() {
  const query = byId("case-search").value.trim().toLowerCase(); const status = byId("case-filter").value;
  return state.cases.filter((item) => (!status || item.status === status) && (!query || JSON.stringify(item).toLowerCase().includes(query)));
}

function renderCases() {
  const rows = filteredCases();
  byId("case-table").innerHTML = rows.length ? rows.map((item) => `<tr class="case-row${state.selectedCase?.case_id === item.case_id ? " selected" : ""}" data-case-id="${escapeHtml(item.case_id)}"><td><strong>${escapeHtml(item.case_id)}</strong><small>${escapeHtml(item.order_id)}</small></td><td>${escapeHtml(item.customer_id)}</td><td>${item.issues.map((issue) => `<span class="issue-chip">${escapeHtml(titleCase(issue.issue_type))}</span>`).join("") || "Needs classification"}</td><td><span class="status-badge ${escapeHtml(item.status)}">${escapeHtml(titleCase(item.status))}</span></td><td>${escapeHtml(formatDate(item.updated_at))}</td></tr>`).join("") : `<tr><td colspan="5" class="table-empty">${state.token ? "No cases match the current filters." : "Open the demo to load persisted cases."}</td></tr>`;
  all(".case-row").forEach((row) => row.addEventListener("click", () => selectCase(row.dataset.caseId)));
}

async function selectCase(caseId) {
  try {
    const [customerCase, timeline] = await Promise.all([apiFetch(`/api/v1/cases/${encodeURIComponent(caseId)}`), apiFetch(`/api/v1/cases/${encodeURIComponent(caseId)}/timeline`)]);
    state.selectedCase = customerCase; state.timeline = timeline; renderCases(); renderCaseDetail(); renderTimeline(); await loadFinalResponse();
  } catch (error) { showToast(error.message, true); }
}

function renderCaseDetail() {
  const item = state.selectedCase; if (!item) return;
  setText("detail-case-id", item.case_id); setStatus("detail-case-status", item.status); setText("detail-customer", item.customer_id); setText("detail-order", item.order_id); setText("detail-opened", formatDate(item.opened_at)); setText("detail-updated", formatDate(item.updated_at)); setText("detail-complaint", item.complaint_text || "This seeded case predates natural-language intake."); setText("audit-case-id", item.case_id);
  byId("detail-issues").innerHTML = item.issues.length ? item.issues.map((issue) => `<div class="issue-row"><div class="issue-number">${escapeHtml(issue.issue_id.split("-").at(-1))}</div><div><strong>${escapeHtml(titleCase(issue.issue_type))}</strong><p>${escapeHtml(titleCase(issue.finding))} · ${escapeHtml(issue.evidence.length)} evidence records · verification ${escapeHtml(titleCase(issue.verification?.status || "pending"))}</p><button class="text-button start-workflow" data-issue-id="${escapeHtml(issue.issue_id)}" type="button">Start investigation</button></div><span class="status-badge ${escapeHtml(issue.status)}">${escapeHtml(titleCase(issue.status))}</span></div>`).join("") : `<div class="empty-state compact">${escapeHtml(item.intake_summary || "No supported issue was classified.")}</div>`;
  all(".start-workflow").forEach((button) => button.addEventListener("click", () => startIssueWorkflow(button.dataset.issueId)));
}

function renderTimeline() {
  const content = state.timeline.length ? state.timeline.map((event) => `<div class="timeline-event"><span class="timeline-dot"></span><div><strong>${escapeHtml(titleCase(event.event_type))}</strong><p>${escapeHtml(event.entity_id)} · ${escapeHtml(summaryForEvent(event))}</p><small>${escapeHtml(formatDate(event.occurred_at))}</small></div></div>`).join("") : `<div class="empty-state compact">No stored events for this case.</div>`;
  byId("case-timeline").innerHTML = content; byId("audit-events").innerHTML = content; byId("reliability-events").innerHTML = content; setText("reliability-trace", state.traceId || "—");
}

function summaryForEvent(event) { const details = event.details || {}; return details.summary || details.outcome || details.note || details.issue_type || details.source || "Stored workflow event"; }

async function loadFinalResponse() {
  const panel = byId("final-response"); panel.hidden = true;
  const workflowIds = [...new Set(state.timeline.filter((event) => event.event_type === "completed" || event.event_type === "escalated").map((event) => event.entity_id))];
  if (!workflowIds.length) return;
  try { const response = await apiFetch(`/api/v1/workflows/${encodeURIComponent(workflowIds.at(-1))}/response`); setText("final-response-text", response.message); panel.hidden = false; } catch (_) { panel.hidden = true; }
}

async function startIssueWorkflow(issueId) {
  const issue = state.selectedCase.issues.find((candidate) => candidate.issue_id === issueId); if (!issue) return;
  const workflowId = `WF-${issueId}-${Date.now()}`; let refundRequest = null;
  if (issue.issue_type === "duplicate_charge" && issue.payment_ids.length > 1) {
    const payments = await apiFetch(`/simulator/v1/orders/${encodeURIComponent(state.selectedCase.order_id)}/payments`); const payment = payments.find((candidate) => candidate.payment_id === issue.payment_ids.at(-1));
    if (payment) refundRequest = { idempotency_key: workflowId, case_id: state.selectedCase.case_id, issue_id: issueId, payment_id: payment.payment_id, amount: payment.amount, currency: payment.currency, kind: "duplicate_charge", reason: "Potential duplicate charge requires controlled investigation" };
  }
  try { const result = await apiFetch("/api/v1/workflows", { method: "POST", body: { workflow_id: workflowId, case_id: state.selectedCase.case_id, issue_id: issueId, refund_request: refundRequest } }); showToast(result.status === "waiting_approval" ? "Workflow paused for approval." : `Workflow finished: ${titleCase(result.outcome)}.`); await Promise.all([loadApprovals(), selectCase(state.selectedCase.case_id)]); }
  catch (error) { showToast(error.message, true); }
}

async function submitComplaint(event) {
  event.preventDefault(); const button = event.submitter; button.disabled = true;
  try { const created = await apiFetch("/api/v1/cases", { method: "POST", body: { customer_id: byId("complaint-customer").value.trim(), order_id: byId("complaint-order").value.trim(), complaint: byId("complaint-text").value.trim() } }); byId("complaint-text").value = ""; await loadCases(); await selectCase(created.case_id); showToast(`Case ${created.case_id} created.`); }
  catch (error) { showToast(error.message, true); } finally { button.disabled = false; }
}

async function loadApprovals() { state.approvals = await apiFetch("/api/v1/approvals"); setText("approval-count", state.approvals.filter((item) => item.status === "pending").length); renderApprovals(); }
function renderApprovals() {
  byId("approval-list").innerHTML = state.approvals.length ? state.approvals.map((item) => `<article class="panel approval-card"><div class="panel-header"><div><p class="eyebrow">${escapeHtml(item.workflow_id)}</p><h2>${escapeHtml(item.approval_id)}</h2></div><span class="status-badge ${escapeHtml(item.status)}">${escapeHtml(titleCase(item.status))}</span></div><div class="detail-grid"><div class="detail-item"><span>Requested action</span><strong>Issue refund</strong></div><div class="detail-item"><span>Amount</span><strong>${escapeHtml(item.amount)} ${escapeHtml(item.currency)}</strong></div><div class="detail-item"><span>Case / issue</span><strong>${escapeHtml(item.case_id)} / ${escapeHtml(item.issue_id)}</strong></div><div class="detail-item"><span>Payment</span><strong>${escapeHtml(item.payment_id)}</strong></div><div class="detail-item"><span>Requested</span><strong>${escapeHtml(formatDate(item.requested_at))}</strong></div><div class="detail-item"><span>Reason</span><strong>${escapeHtml(item.reason)}</strong></div></div>${item.status === "pending" ? `<div class="approval-actions"><input aria-label="Decision note" data-note-for="${escapeHtml(item.approval_id)}" placeholder="Short decision reason"><button class="primary-button approval-decision" data-approval-id="${escapeHtml(item.approval_id)}" data-decision="approve" type="button">Approve</button><button class="secondary-button approval-decision" data-approval-id="${escapeHtml(item.approval_id)}" data-decision="reject" type="button">Reject</button></div>` : `<p class="decision-record">Decision: ${escapeHtml(item.decision_note || "No note")} · ${escapeHtml(formatDate(item.decided_at))}</p>`}</article>`).join("") : `<div class="empty-state">No approval requests are recorded.</div>`;
  all(".approval-decision").forEach((button) => button.addEventListener("click", () => decideApproval(button.dataset.approvalId, button.dataset.decision)));
}
async function decideApproval(approvalId, decision) { const note = document.querySelector(`[data-note-for="${CSS.escape(approvalId)}"]`).value.trim(); if (!note) { showToast("Enter a short decision reason.", true); return; } try { await apiFetch(`/api/v1/approvals/${encodeURIComponent(approvalId)}/decision`, { method: "POST", body: { decision, note } }); showToast(`Approval ${decision === "approve" ? "approved" : "rejected"}.`); await Promise.all([loadApprovals(), state.selectedCase ? selectCase(state.selectedCase.case_id) : Promise.resolve()]); } catch (error) { showToast(error.message, true); } }

async function loadIT() { try { const data = await apiFetch("/simulator/v1/it/cases/ITCASE-2001"); setText("it-employee-name", data.employee.name); setStatus("it-employment", data.employee.status); setText("it-case-id", data.access_case.case_id); setStatus("it-status", data.access_case.status); setText("it-step-identity", `${titleCase(data.identity.status)} · MFA ${data.identity.mfa_enrolled ? "enrolled" : "missing"}`); setText("it-step-approval", data.access_request.approved_by ? `Approved by ${data.access_request.approved_by}` : "Approval pending"); setText("it-step-grant", data.repository_access ? `${titleCase(data.repository_access.status)} ${titleCase(data.repository_access.level)}` : "Not granted"); byId("it-identity").innerHTML = [["Employee ID", data.employee.employee_id], ["Work email", data.employee.work_email], ["Identity", data.identity.username], ["Git account", data.git_account.username], ["Team", data.team.name], ["Repository", data.repository.name]].map(([label, value]) => `<div class="detail-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join(""); byId("it-records").innerHTML = `<div class="record"><div class="record-head"><strong>${escapeHtml(data.access_request.access_request_id)}</strong><span class="status-badge ${escapeHtml(data.access_request.status)}">${escapeHtml(titleCase(data.access_request.status))}</span></div><p>${escapeHtml(data.access_request.justification)}</p></div><div class="record"><div class="record-head"><strong>${escapeHtml(data.ticket.ticket_id)}</strong><span class="status-badge ${escapeHtml(data.ticket.status)}">${escapeHtml(titleCase(data.ticket.status))}</span></div><p>${escapeHtml(data.ticket.subject)}</p></div>`; } catch (error) { showToast(error.message, true); } }

function metricValue(text, name) { return text.split("\n").filter((line) => line.startsWith(name) && !line.startsWith("#")).reduce((sum, line) => sum + (Number(line.trim().split(/\s+/).at(-1)) || 0), 0); }
async function loadMetrics() { try { const text = await apiFetch("/metrics", { text: true }); setText("metric-requests", metricValue(text, "resolveops_http_requests_total")); setText("metric-rejections", metricValue(text, "resolveops_http_rejections_total")); setStatus("metrics-status", "active"); setText("reliability-trace", state.traceId || "—"); } catch (_) { setStatus("metrics-status", "not_loaded"); } }
async function loadAll() { try { await Promise.all([loadCases(), loadApprovals(), loadIT(), loadMetrics()]); setText("last-updated", `Updated ${formatDate(new Date().toISOString())}`); } catch (error) { if (error.status === 401) disconnect(); showToast(error.message, true); } }

function openDialog() { byId("connect-dialog").hidden = false; document.body.classList.add("dialog-open"); byId("api-key").focus(); }
function closeDialog() { byId("connect-dialog").hidden = true; document.body.classList.remove("dialog-open"); byId("connect-error").hidden = true; }
async function secureSignIn(event) { event.preventDefault(); const token = byId("api-key").value.trim(); if (!token) return; state.token = token; try { await apiFetch("/api/v1/cases"); setConnected("operator"); byId("api-key").value = ""; closeDialog(); await loadAll(); } catch (error) { state.token = ""; byId("connect-error").textContent = error.message; byId("connect-error").hidden = false; } }

all(".nav-item").forEach((button) => button.addEventListener("click", () => { all(".nav-item").forEach((item) => item.classList.toggle("active", item === button)); all(".view").forEach((view) => view.classList.toggle("active", view.dataset.viewPanel === button.dataset.view)); byId("mobile-menu").closest(".workspace").previousElementSibling.classList.remove("open"); }));
all(".refresh-button").forEach((button) => button.addEventListener("click", () => state.token ? loadAll() : showToast("Open the demo or sign in first.", true)));
byId("try-demo").addEventListener("click", openDemo); byId("notice-demo").addEventListener("click", openDemo); byId("open-connect").addEventListener("click", openDialog); byId("close-connect").addEventListener("click", closeDialog); byId("connect-form").addEventListener("submit", secureSignIn); byId("disconnect-button").addEventListener("click", disconnect); byId("complaint-form").addEventListener("submit", submitComplaint); byId("case-search").addEventListener("input", renderCases); byId("case-filter").addEventListener("change", renderCases); byId("mobile-menu").addEventListener("click", () => document.querySelector(".sidebar").classList.toggle("open")); byId("toggle-key").addEventListener("click", () => { const input = byId("api-key"); input.type = input.type === "password" ? "text" : "password"; byId("toggle-key").textContent = input.type === "password" ? "Show" : "Hide"; });
window.addEventListener("keydown", (event) => { if (event.key === "Escape") closeDialog(); });
checkHealth();
