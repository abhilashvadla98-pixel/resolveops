"use strict";

const state = {
  token: "",
  traceId: "",
  customerCase: null,
  customer: null,
  order: null,
  payments: [],
  policies: [],
  tickets: [],
  notifications: [],
  it: null,
  metrics: { requests: null, rejections: null, available: false },
};
let connectTrigger = null;

const byId = (id) => document.getElementById(id);
const all = (selector) => Array.from(document.querySelectorAll(selector));

function setText(id, value) {
  const element = byId(id);
  if (element) element.textContent = value ?? "—";
}

function titleCase(value) {
  if (!value) return "—";
  return String(value).replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function statusClass(value) {
  const allowed = new Set([
    "active", "in_progress", "approved", "resolved", "fulfilled", "captured", "ready",
    "pending", "pending_approval", "investigating", "failed", "escalated",
  ]);
  return allowed.has(value) ? value : "neutral";
}

function setStatus(id, value) {
  const element = byId(id);
  if (!element) return;
  element.className = `status-badge ${statusClass(value)}`;
  element.textContent = titleCase(value || "not loaded");
}

function initials(name) {
  if (!name || name === "—") return "—";
  return name.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("en-US", {
    month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit",
  }).format(date);
}

function formatMoney(amount, currency = "USD") {
  const numeric = Number(amount);
  if (!Number.isFinite(numeric)) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(numeric);
}

function setIndicator(id, status) {
  const element = byId(id);
  if (!element) return;
  element.className = status === "ok" ? "ok" : status === "error" ? "error" : "";
}

function showToast(message, isError = false) {
  const toast = byId("toast");
  toast.textContent = message;
  toast.className = `toast show${isError ? " error" : ""}`;
  window.clearTimeout(showToast.timeout);
  showToast.timeout = window.setTimeout(() => { toast.className = "toast"; }, 3200);
}

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function apiFetch(path, { authenticated = true, text = false } = {}) {
  const headers = { Accept: text ? "text/plain" : "application/json" };
  if (authenticated) {
    if (!state.token) throw new ApiError("Connect with an API key first.", 401);
    headers.Authorization = `Bearer ${state.token}`;
  }
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 10000);
  let response;
  try {
    response = await fetch(path, { headers, signal: controller.signal, cache: "no-store" });
  } catch (error) {
    if (error.name === "AbortError") throw new ApiError("The API request timed out.", 408);
    throw new ApiError("The API could not be reached.", 0);
  } finally {
    window.clearTimeout(timeout);
  }
  const traceId = response.headers.get("x-resolveops-trace-id");
  if (traceId) {
    state.traceId = traceId;
    setText("overview-trace", traceId.slice(0, 12));
    setText("reliability-trace", traceId);
  }
  if (!response.ok) {
    let detail = `Request failed with status ${response.status}.`;
    try {
      const body = await response.json();
      if (body.detail) detail = body.detail;
    } catch (_ignored) {
      // Keep the generic status message when a non-JSON proxy response is returned.
    }
    throw new ApiError(detail, response.status);
  }
  return text ? response.text() : response.json();
}

async function loadHealth() {
  const [live, ready] = await Promise.allSettled([
    apiFetch("/health/live", { authenticated: false }),
    apiFetch("/health/ready", { authenticated: false }),
  ]);
  const liveOk = live.status === "fulfilled" && live.value.status === "alive";
  const readyOk = ready.status === "fulfilled" && ready.value.status === "ready";
  setText("live-status", liveOk ? "Healthy" : "Unavailable");
  setText("ready-status", readyOk ? "Ready" : "Not ready");
  setIndicator("live-indicator", liveOk ? "ok" : "error");
  setIndicator("ready-indicator", readyOk ? "ok" : "error");
  byId("health-dot").className = liveOk ? "ok" : "error";
  setText("health-label", liveOk ? (readyOk ? "System ready" : "API live") : "API unavailable");
}

async function loadMetrics() {
  try {
    const text = await apiFetch("/metrics", { text: true });
    state.metrics = {
      requests: sumMetric(text, "resolveops_http_requests_total"),
      rejections: sumMetric(text, "resolveops_http_rejections_total"),
      available: true,
    };
  } catch (error) {
    if (error.status === 403) {
      state.metrics = { requests: null, rejections: null, available: false };
      return;
    }
    throw error;
  }
}

function sumMetric(text, metricName) {
  return text.split("\n")
    .filter((line) => line.startsWith(metricName))
    .reduce((total, line) => {
      const value = Number(line.trim().split(/\s+/).at(-1));
      return total + (Number.isFinite(value) ? value : 0);
    }, 0);
}

async function loadProtectedData() {
  const customerCase = await apiFetch("/simulator/v1/cases/CASE-1001");
  const [customer, order, payments, policies, tickets, notifications, it] = await Promise.all([
    apiFetch(`/simulator/v1/customers/${encodeURIComponent(customerCase.customer_id)}`),
    apiFetch(`/simulator/v1/orders/${encodeURIComponent(customerCase.order_id)}`),
    apiFetch(`/simulator/v1/orders/${encodeURIComponent(customerCase.order_id)}/payments`),
    apiFetch("/simulator/v1/policies"),
    apiFetch(`/simulator/v1/cases/${encodeURIComponent(customerCase.case_id)}/tickets`),
    apiFetch(`/simulator/v1/cases/${encodeURIComponent(customerCase.case_id)}/notifications`),
    apiFetch("/simulator/v1/it/cases/ITCASE-2001"),
  ]);
  state.customerCase = customerCase;
  state.customer = customer;
  state.order = order;
  state.payments = payments;
  state.policies = policies;
  state.tickets = tickets;
  state.notifications = notifications;
  state.it = it;
  await loadMetrics();
  renderAll();
}

async function refreshAll() {
  const buttons = all(".refresh-button");
  buttons.forEach((button) => { button.disabled = true; });
  try {
    await loadHealth();
    if (state.token) await loadProtectedData();
    setText("last-updated", `Updated ${new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit", second: "2-digit" }).format(new Date())}`);
    if (state.token) showToast("Live operational data refreshed.");
  } catch (error) {
    showToast(error.message || "Refresh failed.", true);
    if (error.status === 401) disconnect(false);
  } finally {
    buttons.forEach((button) => { button.disabled = false; });
  }
}

function renderAll() {
  renderOverview();
  renderCustomer();
  renderEmployee();
  renderReliability();
}

function renderOverview() {
  const customerCase = state.customerCase;
  const it = state.it;
  if (!customerCase || !it) return;
  const evidenceCount = customerCase.issues.reduce((sum, issue) => sum + issue.evidence.length, 0);
  setText("kpi-issues", customerCase.issues.length);
  setText("kpi-issues-note", `${customerCase.issues.filter((issue) => issue.status !== "resolved").length} require investigation`);
  setText("kpi-evidence", evidenceCount);
  setText("kpi-access", titleCase(it.access_request.status));
  setText("kpi-access-note", `${titleCase(it.access_request.requested_level)} access to ${it.repository.name}`);
  setText("kpi-requests", state.metrics.available ? Math.round(state.metrics.requests) : "Restricted");
  setText("kpi-rejections", state.metrics.available ? `${Math.round(state.metrics.rejections)} pre-processing rejections` : "Operations role required for metrics");
  setText("overview-case-id", customerCase.case_id);
  setStatus("overview-case-status", customerCase.status);
  setText("overview-customer", state.customer.name);
  setText("overview-order", customerCase.order_id);
  setText("overview-value", formatMoney(state.order.total_amount, state.order.currency));
  renderIssueRows("overview-issues", customerCase.issues);

  setStatus("overview-it-status", it.access_request.status);
  setText("overview-employee", it.employee.name);
  setText("overview-employee-email", it.employee.work_email);
  setText("overview-employee-avatar", initials(it.employee.name));
  setText("overview-repository", it.repository.name);
  setText("overview-access-level", `Requested access: ${titleCase(it.access_request.requested_level)}`);
  const approved = Boolean(it.access_request.approved_by && it.access_request.approved_at);
  setText("overview-approval", approved ? "Persisted approval verified" : "Approval evidence missing");
  setText("overview-approver", approved ? `${it.access_request.approved_by} · ${formatDate(it.access_request.approved_at)}` : "The workflow must stop for review.");
}

function renderIssueRows(containerId, issues) {
  const container = byId(containerId);
  const rows = issues.map((issue, index) => {
    const row = element("div", "issue-row");
    row.append(element("span", "issue-number", String(index + 1).padStart(2, "0")));
    const body = element("div");
    body.append(element("strong", "", titleCase(issue.issue_type)));
    const finding = titleCase(issue.finding);
    body.append(element("p", "", `${titleCase(issue.status)} · Finding: ${finding}`));
    row.append(body);
    row.append(element("span", "evidence-count", `${issue.evidence.length} evidence record${issue.evidence.length === 1 ? "" : "s"}`));
    return row;
  });
  container.replaceChildren(...rows);
}

function renderCustomer() {
  const customerCase = state.customerCase;
  if (!customerCase) return;
  setText("customer-case-heading", customerCase.case_id);
  setStatus("customer-status", customerCase.status);
  renderDetails("customer-summary", [
    ["Customer", state.customer.name],
    ["Order", customerCase.order_id],
    ["Case opened", formatDate(customerCase.opened_at)],
    ["Order total", formatMoney(state.order.total_amount, state.order.currency)],
    ["Issues", String(customerCase.issues.length)],
    ["Last updated", formatDate(customerCase.updated_at)],
  ]);
  renderIssueRows("customer-issues", customerCase.issues);
  renderRecords("payment-list", state.payments.map((payment) => ({
    title: payment.payment_id,
    status: payment.status,
    description: `${formatMoney(payment.amount, payment.currency)} · ${titleCase(payment.status)}`,
    meta: [formatDate(payment.captured_at || payment.created_at)],
  })));
  renderRecords("policy-list", state.policies.map((policy) => ({
    title: policy.title,
    status: policy.status,
    description: policy.content,
    meta: [`v${policy.version}`, policy.policy_id],
  })));
  const communications = [
    ...state.tickets.map((ticket) => ({ title: ticket.subject, status: ticket.status, description: ticket.description, meta: [ticket.ticket_id] })),
    ...state.notifications.map((notification) => ({ title: `Notification · ${titleCase(notification.channel)}`, status: notification.status, description: notification.message, meta: [notification.notification_id, formatDate(notification.sent_at)] })),
  ];
  renderRecords("communication-list", communications);
}

function renderEmployee() {
  const it = state.it;
  if (!it) return;
  setText("employee-avatar", initials(it.employee.name));
  setText("employee-name", it.employee.name);
  setText("employee-email", it.employee.work_email);
  setText("employment-status", titleCase(it.employee.status));
  setText("identity-status", titleCase(it.identity.status));
  setText("mfa-status", it.identity.mfa_enrolled ? "Enrolled" : "Missing");
  setText("git-status", titleCase(it.git_account.status));
  setText("access-request-id", it.access_request.access_request_id);
  setStatus("access-status", it.access_request.status);
  setText("path-employment", it.employee.status === "active" ? "Active employee verified" : "Employment requires review");
  setText("path-approval", it.access_request.approved_by ? "Approval evidence verified" : "Approval missing");
  setText("path-grant", it.repository_access ? "Access record present" : "Grant not yet verified");
  renderDetails("access-details", [
    ["Case", it.access_case.case_id],
    ["Team", it.team.name],
    ["Repository", it.repository.name],
    ["Requested level", titleCase(it.access_request.requested_level)],
    ["Ticket", it.ticket.ticket_id],
    ["Case status", titleCase(it.access_case.status)],
  ]);
  const approved = Boolean(it.access_request.approved_by && it.access_request.approved_at);
  setText("approval-title", approved ? "Human approval evidence is persisted" : "Human approval is required");
  setText("approval-detail", approved ? `${it.access_request.approved_by} approved at ${formatDate(it.access_request.approved_at)}` : "The deterministic workflow must stop before execution.");
  const repositoryRecords = [
    { title: it.repository.name, status: "active", description: `Owned by ${it.team.name}; requires directory group ${it.repository.required_group_id}.`, meta: [it.repository.repository_id] },
    { title: "Directory membership", status: it.group_membership?.status || "pending", description: it.group_membership ? `Membership ${it.group_membership.membership_id} is present.` : "No required group membership is present.", meta: [it.identity.username] },
    { title: "Repository access", status: it.repository_access?.status || "pending", description: it.repository_access ? `${titleCase(it.repository_access.level)} access has a persisted record.` : "No verified repository grant exists yet.", meta: [it.git_account.username] },
  ];
  renderRecords("repository-controls", repositoryRecords);
  const serviceRecords = [
    { title: it.ticket.subject, status: it.ticket.status, description: it.ticket.description, meta: [it.ticket.ticket_id, formatDate(it.ticket.updated_at)] },
    ...it.notifications.map((notification) => ({ title: "Employee notification", status: notification.status, description: notification.message, meta: [notification.notification_id, formatDate(notification.sent_at)] })),
  ];
  renderRecords("it-service-records", serviceRecords);
}

function renderReliability() {
  setText("metric-requests", state.metrics.available ? Math.round(state.metrics.requests) : "Restricted");
  setText("metric-rejections", state.metrics.available ? Math.round(state.metrics.rejections) : "Restricted");
  setStatus("metrics-status", state.metrics.available ? "ready" : "neutral");
}

function renderDetails(containerId, pairs) {
  const nodes = pairs.map(([label, value]) => {
    const item = element("div", "detail-item");
    item.append(element("span", "", label), element("strong", "", value));
    return item;
  });
  byId(containerId).replaceChildren(...nodes);
}

function renderRecords(containerId, records) {
  const container = byId(containerId);
  if (!records.length) {
    container.replaceChildren(element("div", "empty-state compact", "No records found."));
    return;
  }
  const nodes = records.map((record) => {
    const wrapper = element("div", "record");
    const head = element("div", "record-head");
    head.append(element("strong", "", record.title));
    const badge = element("span", `status-badge ${statusClass(record.status)}`, titleCase(record.status));
    head.append(badge);
    wrapper.append(head, element("p", "", record.description));
    const meta = element("div", "record-meta");
    (record.meta || []).forEach((value) => meta.append(element("span", "", value)));
    wrapper.append(meta);
    return wrapper;
  });
  container.replaceChildren(...nodes);
}

function element(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== "") node.textContent = text;
  return node;
}

function setConnected(connected) {
  byId("sidebar-pulse").classList.toggle("connected", connected);
  setText("sidebar-connection", connected ? "API connected" : "Not connected");
  byId("disconnect-button").hidden = !connected;
  byId("open-connect").textContent = connected ? "Change connection" : "Connect securely";
  const notice = byId("connection-notice");
  notice.classList.toggle("connected", connected);
  notice.querySelector("strong").textContent = connected ? "Live secured data connected" : "Connect to the secured demo API";
  notice.querySelector("p").textContent = connected ? "Data comes from authenticated tenant-isolated simulator APIs." : "Paste a configured operator API key. It stays in browser memory only and disappears when this page closes.";
  notice.querySelector("button").textContent = connected ? "Reconnect" : "Connect";
}

function disconnect(showMessage = true) {
  state.token = "";
  state.customerCase = null;
  state.customer = null;
  state.order = null;
  state.payments = [];
  state.policies = [];
  state.tickets = [];
  state.notifications = [];
  state.it = null;
  state.metrics = { requests: null, rejections: null, available: false };
  setConnected(false);
  setText("last-updated", "Waiting for connection");
  if (showMessage) showToast("The in-memory API key was cleared.");
}

function closeConnectDialog() {
  const dialog = byId("connect-dialog");
  dialog.hidden = true;
  document.body.classList.remove("dialog-open");
  if (connectTrigger) connectTrigger.focus();
}

function openConnectDialog() {
  const dialog = byId("connect-dialog");
  connectTrigger = document.activeElement;
  byId("connect-error").hidden = true;
  byId("api-key").value = "";
  dialog.hidden = false;
  document.body.classList.add("dialog-open");
  window.setTimeout(() => byId("api-key").focus(), 50);
}

function selectView(name) {
  all(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === name));
  all(".view").forEach((view) => view.classList.toggle("active", view.dataset.viewPanel === name));
  byId("main-content").focus({ preventScroll: true });
  window.scrollTo({ top: 0, behavior: "smooth" });
  document.querySelector(".sidebar").classList.remove("open");
}

function bindEvents() {
  all(".nav-item").forEach((item) => item.addEventListener("click", () => selectView(item.dataset.view)));
  all(".connect-trigger").forEach((button) => button.addEventListener("click", openConnectDialog));
  byId("open-connect").addEventListener("click", openConnectDialog);
  byId("close-connect").addEventListener("click", closeConnectDialog);
  byId("disconnect-button").addEventListener("click", () => disconnect(true));
  all(".refresh-button").forEach((button) => button.addEventListener("click", refreshAll));
  byId("mobile-menu").addEventListener("click", () => document.querySelector(".sidebar").classList.toggle("open"));
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !byId("connect-dialog").hidden) closeConnectDialog();
  });
  byId("toggle-key").addEventListener("click", () => {
    const input = byId("api-key");
    const visible = input.type === "text";
    input.type = visible ? "password" : "text";
    byId("toggle-key").textContent = visible ? "Show" : "Hide";
  });
  byId("connect-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = byId("api-key");
    const errorBox = byId("connect-error");
    const submit = byId("connect-submit");
    const token = input.value.trim();
    if (token.length < 20) {
      errorBox.textContent = "Enter a configured ResolveOps API key.";
      errorBox.hidden = false;
      return;
    }
    state.token = token;
    input.value = "";
    submit.disabled = true;
    submit.textContent = "Connecting…";
    errorBox.hidden = true;
    try {
      await loadProtectedData();
      setConnected(true);
      closeConnectDialog();
      setText("last-updated", `Updated ${new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" }).format(new Date())}`);
      showToast("Secure operator session connected.");
    } catch (error) {
      state.token = "";
      errorBox.textContent = error.status === 401 ? "Authentication failed. Check the API key and try again." : (error.message || "Connection failed.");
      errorBox.hidden = false;
    } finally {
      submit.disabled = false;
      submit.textContent = "Connect and load live data";
    }
  });
}

async function initialize() {
  bindEvents();
  setConnected(false);
  await loadHealth();
}

initialize().catch(() => showToast("The health endpoint could not be reached.", true));
