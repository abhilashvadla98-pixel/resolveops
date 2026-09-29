from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()

CONSOLE_ROOT = Path(__file__).resolve().parent.parent / "interfaces" / "operator_console"
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


@router.get("/console", include_in_schema=False)
def operator_console() -> FileResponse:
    return FileResponse(
        CONSOLE_ROOT / "index.html",
        media_type="text/html",
        headers={**SECURITY_HEADERS, "Cache-Control": "no-store"},
    )


@router.get("/console/app.css", include_in_schema=False)
def operator_console_styles() -> FileResponse:
    return FileResponse(
        CONSOLE_ROOT / "app.css",
        media_type="text/css",
        headers={**SECURITY_HEADERS, "Cache-Control": "public, max-age=3600"},
    )


@router.get("/console/app.js", include_in_schema=False)
def operator_console_script() -> FileResponse:
    return FileResponse(
        CONSOLE_ROOT / "app.js",
        media_type="text/javascript",
        headers={**SECURITY_HEADERS, "Cache-Control": "no-store"},
    )
