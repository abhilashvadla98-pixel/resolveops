from fastapi.testclient import TestClient

from resolveops.api.main import app


def test_operator_console_serves_secure_shell_and_local_assets() -> None:
    with TestClient(app) as client:
        page = client.get("/console")
        styles = client.get("/console/app.css")
        script = client.get("/console/app.js")

    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    assert page.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in page.headers["content-security-policy"]
    assert "ResolveOps | Operations Console" in page.text
    assert ">Customer Operations<" in page.text
    assert ">Overview<" in page.text
    assert ">Approvals<" in page.text
    assert ">Employee IT<" in page.text
    assert ">Audit<" in page.text
    assert "Open customer workflow" in page.text
    assert "Open employee IT workflow" in page.text
    assert "Checking whether live specialist reasoning is available" in page.text
    assert 'src="/console/app.js?v=20261004b"' in page.text
    assert 'id="inference-mode"' in page.text
    assert 'src="/console/it_intake.js?v=20261004a"' in page.text
    assert 'href="/console/app.css?v=20261004b"' in page.text
    assert 'role="dialog"' in page.text
    assert 'aria-modal="true"' in page.text
    assert styles.status_code == 200
    assert styles.headers["content-type"].startswith("text/css")
    assert "--accent:#2457a7" in styles.text
    assert "--bg:#f6f7f9" in styles.text
    assert "glow" not in styles.text
    assert script.status_code == 200
    assert "Investigate · live agents when available" in script.text
    assert "agent_call_count" in script.text
    assert "agent_run_ids" in script.text
    assert "Persisted execution records" in script.text
    assert "/agent-workflows/${encodeURIComponent(workflowId)}/runs" in script.text
    assert "renderStoppedAgentRuns(workflow)" in script.text
    assert "stopped safely before control-plane handoff" in script.text
    assert script.headers["cache-control"] == "no-store"
    assert "localStorage" not in script.text
    assert "sessionStorage" not in script.text
    assert "state.token = token" in script.text
    assert "Authorization" in script.text
    assert 'apiFetch("/api/v1/demo/session"' in script.text
    assert "timeoutMs: 90000" in script.text
    assert "Starting free demo · first visit can take about a minute" in script.text
    assert 'button.textContent = "Starting service…"' in script.text
    assert "renderOverview(); openDemo();" in script.text
    assert "apiFetch(`/api/v1/case-queue?" in script.text
    assert 'apiFetch("/api/v1/approvals"' in script.text
    assert 'apiFetch("/api/v1/reliability/summary"' in script.text
    assert "Run multi-agent analysis" not in page.text
    assert 'apiFetch("/api/v1/agent-workflows/jobs"' not in script.text
    assert "Specialist review · decision support only" in page.text
    assert "CSS.escape" in script.text
    assert "Investigation stopped safely" in script.text
    assert "Investigation status needs refresh" in script.text
    assert "timeoutMs: 90000" in script.text
    assert "Retry investigation" in script.text
    assert "Why this is a duplicate candidate" in script.text
    assert "No approval created" in script.text
    assert "ResolveOps stopped before approval or execution" in script.text
    assert "renderWorkflowFailure(issueId, error)" in script.text


def test_product_home_redirects_to_operator_console() -> None:
    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/")

    assert response.status_code == 307
    assert response.headers["location"] == "/console"
    assert response.headers["cache-control"] == "no-store"


def test_console_assets_are_not_listed_as_public_api_operations() -> None:
    schema = app.openapi()

    assert "/console" not in schema["paths"]
    assert "/console/app.css" not in schema["paths"]
    assert "/console/app.js" not in schema["paths"]
    assert "/" not in schema["paths"]
