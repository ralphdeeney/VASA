"""Serve the small first-party dashboard without a template dependency."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from vasa.contracts.models import TenantContext
from vasa.control.auth import require_context

router = APIRouter(include_in_schema=False)
_ROOT = Path(__file__).parent
_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src data:; "
        "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


@router.get("/login")
async def login_page() -> FileResponse:
    return FileResponse(_ROOT / "templates" / "login.html", headers=_HEADERS)


@router.get("/dashboard")
async def dashboard_page(
    _context: Annotated[TenantContext, Depends(require_context)],
) -> FileResponse:
    return FileResponse(_ROOT / "templates" / "dashboard.html", headers=_HEADERS)


@router.get("/dashboard/assets/styles.css")
async def stylesheet() -> FileResponse:
    return FileResponse(_ROOT / "assets" / "styles.css", headers=_HEADERS)


@router.get("/dashboard/assets/login.js")
async def login_script() -> FileResponse:
    return FileResponse(
        _ROOT / "assets" / "login.js", media_type="text/javascript", headers=_HEADERS
    )


@router.get("/dashboard/assets/dashboard.js")
async def dashboard_script() -> FileResponse:
    return FileResponse(
        _ROOT / "assets" / "dashboard.js", media_type="text/javascript", headers=_HEADERS
    )
