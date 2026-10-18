"""Serve the small first-party dashboard without a template dependency."""

import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from vasa.contracts.models import TenantContext
from vasa.control.auth import require_context

router = APIRouter(include_in_schema=False)
_ROOT = Path(__file__).parent
_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
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


@router.get("/")
@router.get("/features")
@router.get("/how-it-works")
@router.get("/pricing")
@router.get("/contact")
async def public_page() -> FileResponse:
    return FileResponse(_ROOT / "templates" / "site.html", headers=_HEADERS)


@router.get("/signup")
@router.get("/verify-email")
@router.get("/resend-verification")
@router.get("/forgot-password")
@router.get("/reset-password")
@router.get("/accept-invitation")
@router.get("/logout")
async def identity_page(request: Request) -> HTMLResponse:
    # Only fixed first-party fragments vary by route; no request text is interpolated.
    is_signup = request.url.path == "/signup"
    template = await asyncio.to_thread(
        (_ROOT / "templates" / "identity.html").read_text, encoding="utf-8"
    )
    navigation = "" if is_signup else '<a class="button" href="/signup">Get started</a>'
    logo = (
        '<img src="/dashboard/assets/vasa-logo.png" alt="VASA" class="identity-logo">'
        if is_signup
        else ""
    )
    help_text = (
        'Already have an account? <a href="/login">Sign in</a>'
        if is_signup
        else '<a href="/login">Sign in</a> · <a href="/signup">Create account</a>'
    )
    return HTMLResponse(
        template.replace("<!-- identity-signup-navigation -->", navigation)
        .replace("<!-- identity-account-help -->", help_text)
        .replace("<!-- identity-brand-logo -->", logo),
        headers=_HEADERS,
    )


@router.get("/403", status_code=403)
@router.get("/404", status_code=404)
async def error_page(request: Request) -> FileResponse:
    code = 403 if request.url.path == "/403" else 404
    return FileResponse(_ROOT / "templates" / "error.html", status_code=code, headers=_HEADERS)


@router.get("/admin")
async def admin_page(request: Request) -> FileResponse:
    if not request.app.state.settings.saas_enabled:
        raise HTTPException(status_code=404, detail="not_found")
    from vasa.saas.permissions import require_platform_admin

    await require_platform_admin(request)
    return FileResponse(_ROOT / "templates" / "admin.html", headers=_HEADERS)


@router.get("/dashboard/assets/site.js")
@router.get("/dashboard/assets/identity.js")
@router.get("/dashboard/assets/workspace.js")
@router.get("/dashboard/assets/admin.js")
async def site_script(request: Request) -> FileResponse:
    # The route set is explicit; this cannot select arbitrary filesystem paths.
    filename = request.url.path.rsplit("/", 1)[-1]
    return FileResponse(_ROOT / "assets" / filename, media_type="text/javascript", headers=_HEADERS)


@router.get("/dashboard/assets/vasa-logo.png")
async def identity_logo() -> FileResponse:
    return FileResponse(
        _ROOT / "assets" / "vasa-logo.png", media_type="image/png", headers=_HEADERS
    )


@router.get("/admin/login")
async def admin_login_page(request: Request) -> FileResponse:
    if not request.app.state.settings.saas_enabled:
        raise HTTPException(status_code=404, detail="not_found")
    return FileResponse(_ROOT / "templates" / "admin-login.html", headers=_HEADERS)


@router.get("/dashboard/assets/admin.css")
async def admin_styles() -> FileResponse:
    return FileResponse(_ROOT / "assets" / "admin.css", headers=_HEADERS)


@router.get("/dashboard/assets/admin-login.js")
async def admin_login_script() -> FileResponse:
    return FileResponse(
        _ROOT / "assets" / "admin-login.js", media_type="text/javascript", headers=_HEADERS
    )
