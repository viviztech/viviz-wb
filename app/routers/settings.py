from pathlib import Path

import httpx
import markdown
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings, check_insecure_defaults, EDITABLE_SETTINGS
from app.database import get_db
from app.services.app_settings import save_override
from app.services.audit import log_event

router = APIRouter(prefix="/settings", tags=["settings"])
templates = Jinja2Templates(directory="app/templates")

WABA_SETUP_DOC = Path(__file__).resolve().parent.parent.parent / "docs" / "WABA_SETUP.md"


def _mask(value: str, keep: int = 4) -> str:
    """Show only the last few characters of a secret, e.g. ****************ab12."""
    if not value:
        return ""
    if len(value) <= keep:
        return "*" * len(value)
    return "*" * (len(value) - keep) + value[-keep:]


def _field(label: str, key: str, value: str, secret: bool = False, insecure: bool = False, editable: bool = False):
    return {
        "label": label,
        "key": key,
        "set": bool(value),
        "display": (_mask(value) if secret else value) if value else "",
        "raw": "" if secret else (value or ""),
        "insecure": insecure,
        "secret": secret,
        "editable": editable,
    }


def _build_sections() -> list[dict]:
    insecure = set(check_insecure_defaults(settings))

    return [
        {
            "name": "Meta WhatsApp Business API",
            "icon": "fa-whatsapp",
            "fields": [
                _field("Phone Number ID", "whatsapp_phone_number_id", settings.whatsapp_phone_number_id, editable=True),
                _field("WhatsApp Business Account ID", "whatsapp_business_account_id", settings.whatsapp_business_account_id, editable=True),
                _field("Access Token", "whatsapp_access_token", settings.whatsapp_access_token, secret=True, editable=True),
                _field(
                    "Webhook Verify Token", "whatsapp_webhook_verify_token", settings.whatsapp_webhook_verify_token,
                    insecure="whatsapp_webhook_verify_token" in insecure, editable=True,
                ),
                _field("Meta App ID", "meta_app_id", settings.meta_app_id, editable=True),
                _field("Meta App Secret", "meta_app_secret", settings.meta_app_secret, secret=True, editable=True),
            ],
        },
        {
            "name": "Application & Security",
            "icon": "fa-shield-alt",
            "fields": [
                _field("App URL", "app_url", settings.app_url, editable=True),
                _field(
                    "Secret Key", "secret_key", settings.secret_key, secret=True,
                    insecure="secret_key" in insecure,
                ),
                _field("Admin Email", "admin_email", settings.admin_email),
                _field(
                    "Admin Password", "admin_password", settings.admin_password, secret=True,
                    insecure="admin_password" in insecure,
                ),
                _field("Debug Mode", "debug", "on" if settings.debug else "off"),
                _field("Allowed Origins (CORS)", "allowed_origins", settings.allowed_origins),
            ],
        },
        {
            "name": "Database & Cache",
            "icon": "fa-database",
            "fields": [
                _field("Database URL", "database_url", settings.database_url, secret=True),
                _field("Redis URL", "redis_url", settings.redis_url, secret=True),
            ],
        },
        {
            "name": "Claude AI",
            "icon": "fa-robot",
            "fields": [
                _field("Anthropic API Key", "anthropic_api_key", settings.anthropic_api_key, secret=True, editable=True),
            ],
        },
        {
            "name": "AWS S3 (media storage)",
            "icon": "fa-cloud",
            "fields": [
                _field("AWS Access Key ID", "aws_access_key_id", settings.aws_access_key_id, secret=True, editable=True),
                _field("AWS Secret Access Key", "aws_secret_access_key", settings.aws_secret_access_key, secret=True, editable=True),
                _field("AWS Region", "aws_region", settings.aws_region, editable=True),
                _field("S3 Bucket Name", "s3_bucket_name", settings.s3_bucket_name, editable=True),
            ],
        },
    ]


@router.get("", response_class=HTMLResponse)
async def settings_page(request: Request, saved: str = ""):
    if not request.session.get("admin_email"):
        return RedirectResponse("/login", status_code=302)

    sections = _build_sections()
    total_fields = sum(len(s["fields"]) for s in sections)
    missing = sum(1 for s in sections for f in s["fields"] if not f["set"])

    return templates.TemplateResponse("dashboard/settings.html", {
        "request": request,
        "admin_name": request.session.get("admin_name", "Admin"),
        "page": "settings",
        "sections": sections,
        "total_fields": total_fields,
        "missing": missing,
        "saved": bool(saved),
        "webhook_callback_url": f"{settings.app_url.rstrip('/')}/webhook",
    })


@router.post("/update")
async def update_settings(request: Request, db: AsyncSession = Depends(get_db)):
    admin_email = request.session.get("admin_email")
    if not admin_email:
        return RedirectResponse("/login", status_code=302)

    form = await request.form()
    changed = []
    for key in EDITABLE_SETTINGS:
        if key not in form:
            continue
        new_value = form[key].strip()
        if not new_value:
            continue  # blank means "leave unchanged" — lets secret inputs stay empty in the UI
        if new_value != getattr(settings, key):
            await save_override(db, key, new_value)
            changed.append(key)

    if changed:
        await log_event(
            db, actor=admin_email, action="settings_update",
            target_type="app_setting", meta={"fields": changed},
        )

    return RedirectResponse("/settings?saved=1", status_code=302)


@router.get("/guide", response_class=HTMLResponse)
async def settings_guide(request: Request):
    if not request.session.get("admin_email"):
        return RedirectResponse("/login", status_code=302)

    if WABA_SETUP_DOC.exists():
        raw = WABA_SETUP_DOC.read_text(encoding="utf-8")
        content_html = markdown.markdown(raw, extensions=["tables", "fenced_code", "toc"])
    else:
        content_html = "<p>docs/WABA_SETUP.md was not found on the server.</p>"

    return templates.TemplateResponse("dashboard/settings_guide.html", {
        "request": request,
        "admin_name": request.session.get("admin_name", "Admin"),
        "page": "settings",
        "content_html": content_html,
    })


@router.post("/test-connection")
async def test_connection(request: Request):
    """Calls the Meta Graph API with the configured credentials to confirm they actually work."""
    if not request.session.get("admin_email"):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    if not settings.whatsapp_phone_number_id or not settings.whatsapp_access_token:
        return JSONResponse({
            "ok": False,
            "error": "Phone Number ID and Access Token must both be set in .env before testing.",
        }, status_code=400)

    url = f"{settings.whatsapp_api_url}/{settings.whatsapp_phone_number_id}"
    params = {"fields": "verified_name,display_phone_number,quality_rating,code_verification_status"}
    headers = {"Authorization": f"Bearer {settings.whatsapp_access_token}"}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, params=params, headers=headers)
        if r.status_code == 200:
            data = r.json()
            return JSONResponse({
                "ok": True,
                "verified_name": data.get("verified_name"),
                "display_phone_number": data.get("display_phone_number"),
                "quality_rating": data.get("quality_rating"),
                "code_verification_status": data.get("code_verification_status"),
            })
        else:
            detail = r.json().get("error", {}).get("message", r.text) if r.headers.get("content-type", "").startswith("application/json") else r.text
            return JSONResponse({"ok": False, "error": detail}, status_code=502)
    except httpx.RequestError as ex:
        return JSONResponse({"ok": False, "error": f"Could not reach Meta Graph API: {ex}"}, status_code=502)
