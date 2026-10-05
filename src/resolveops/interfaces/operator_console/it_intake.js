"use strict";

(() => {
  let sourceMessageId = "";
  let options = null;
  let submitting = false;
  const panel = byId("it-intake-panel");
  const form = byId("it-intake-form");

  function closeIntake() {
    if (submitting) return;
    panel.hidden = true;
    sourceMessageId = "";
    form.reset();
  }

  byId("new-it-request").addEventListener("click", async () => {
    try {
      options = await apiFetch("/api/v1/it/request-options");
      byId("it-intake-employee").innerHTML = options.employees.map((item) => `<option value="${escapeHtml(item.employee_id)}">${escapeHtml(item.name)} · ${escapeHtml(item.employee_id)}</option>`).join("");
      byId("it-intake-employee").disabled = !options.demo_personas_enabled;
      byId("it-intake-repository").innerHTML = options.repositories.map((item) => `<option value="${escapeHtml(item.repository_id)}">${escapeHtml(item.name)}</option>`).join("");
      byId("it-intake-level").innerHTML = options.allowed_levels.map((level) => `<option value="${escapeHtml(level)}">${escapeHtml(titleCase(level))}</option>`).join("");
      setText("it-intake-mode", options.demo_personas_enabled
        ? `Sandbox: choose a fictional employee. Approval simulates their team manager and records that simulation explicitly. ${options.execution_mode === "live_model" ? "Gemini specialists investigate the ticket; code controls approval and access." : "This session uses rules only."}`
        : `Your authenticated identity determines the requester. Only the actual target-team manager can approve. ${options.execution_mode === "live_model" ? "Gemini specialists investigate the ticket; code controls approval and access." : "This session uses rules only."}`);
      if (!sourceMessageId) sourceMessageId = `IT-MSG-${crypto.randomUUID()}`;
      byId("it-intake-error").hidden = true;
      panel.hidden = false;
      panel.scrollIntoView({behavior: "smooth", block: "nearest"});
    } catch (error) {
      showToast(error.message, true);
    }
  });
  byId("cancel-it-request").addEventListener("click", closeIntake);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (submitting || !options || !form.reportValidity()) return;
    submitting = true;
    byId("submit-it-request").disabled = true;
    byId("it-intake-error").hidden = true;
    const body = {
      source_message_id: sourceMessageId,
      repository_id: byId("it-intake-repository").value,
      requested_level: byId("it-intake-level").value,
      justification: byId("it-intake-reason").value.trim(),
    };
    if (options.demo_personas_enabled) body.demo_employee_id = byId("it-intake-employee").value;
    try {
      const created = await apiFetch("/api/v1/it/requests", {method: "POST", body});
      sourceMessageId = "";
      panel.hidden = true;
      form.reset();
      await Promise.all([loadITQueue(), loadApprovals()]);
      await selectITCase(created.access_case.case_id);
      showToast("Access request received. Review the manager approval before processing.");
    } catch (error) {
      setText("it-intake-error", `${error.message} Retrying this form uses the same receipt ID. Cancel to start a different request.`);
      byId("it-intake-error").hidden = false;
    } finally {
      submitting = false;
      byId("submit-it-request").disabled = false;
    }
  });

  window.loadITAttemptHistory = async (caseId) => {
    const target = byId("it-attempt-history");
    target.innerHTML = '<p class="empty-state">Loading attempts…</p>';
    try {
      const attempts = await apiFetch(`/api/v1/it/cases/${encodeURIComponent(caseId)}/workflows`);
      if (state.selectedITCase !== caseId) return;
      target.innerHTML = attempts.length ? attempts.map((attempt, index) => `<div class="record"><strong>${index === 0 ? "Latest · " : ""}${escapeHtml(titleCase(attempt.outcome))}</strong><p>${escapeHtml(attempt.resolution_summary)}</p><small>${escapeHtml(formatDate(attempt.created_at))} · ${escapeHtml(attempt.workflow_id)}</small>${attempt.error_code ? `<p>Recovery: ${escapeHtml(attempt.error_message)}</p>` : ""}</div>`).join("") : '<p class="empty-state">No processing attempt yet. Approval and processing are separate steps.</p>';
    } catch (error) {
      target.textContent = error.message;
    }
  };
})();
