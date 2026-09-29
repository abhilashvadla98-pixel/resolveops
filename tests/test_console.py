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
    assert ">Cases<" in page.text
    assert ">Approvals<" in page.text
    assert ">IT Requests<" in page.text
    assert ">Audit<" in page.text
    assert ">Try demo<" in page.text
    assert 'src="/console/app.js?v=20260929b"' in page.text
    assert 'role="dialog"' in page.text
    assert 'aria-modal="true"' in page.text
    assert styles.status_code == 200
    assert styles.headers["content-type"].startswith("text/css")
    assert "--accent:#2457a7" in styles.text
    assert "--bg:#f6f7f9" in styles.text
    assert "glow" not in styles.text
    assert script.status_code == 200
    assert script.headers["cache-control"] == "no-store"
    assert "localStorage" not in script.text
    assert "sessionStorage" not in script.text
    assert "state.token = token" in script.text
    assert "Authorization" in script.text
    assert 'apiFetch("/api/v1/demo/session"' in script.text
    assert "apiFetch(`/api/v1/case-queue?" in script.text
    assert 'apiFetch("/api/v1/approvals"' in script.text
    assert 'apiFetch("/api/v1/reliability/summary"' in script.text
    assert "CSS.escape" in script.text


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
