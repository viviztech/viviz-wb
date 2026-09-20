import logging
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.mm_lite import MMLiteOnboarding
from app.services.mm_lite import (
    get_marketing_api_readiness,
    meta_app_dashboard_url,
    subscribe_marketing_webhook,
)

router = APIRouter(prefix="/mm-lite", tags=["mm_lite"])
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)


def _auth(request: Request):
    return request.session.get("admin_email")


def _safe_meta_error(ex: Exception) -> str:
    """Return an actionable API error without credentials or request URLs."""
    if isinstance(ex, httpx.HTTPStatusError):
        try:
            error = ex.response.json().get("error", {})
            message = error.get("message", "Meta rejected the request")
            code = error.get("code")
            return f"Meta API error {code}: {message}" if code else message
        except Exception:
            return f"Meta API returned HTTP {ex.response.status_code}"
    if isinstance(ex, ValueError):
        return str(ex)
    return "Could not connect to Meta. Check the configured IDs and access token."


@router.get("", response_class=HTMLResponse)
async def mm_lite_page(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return RedirectResponse("/login", status_code=302)

    record = await _get_onboarding_record(db)
    connection = None
    connection_error = None
    if settings.whatsapp_phone_number_id and settings.whatsapp_access_token:
        try:
            connection = await get_marketing_api_readiness()
        except Exception as ex:
            connection_error = _safe_meta_error(ex)
            logger.warning("Marketing Messages credential check failed: %s", connection_error)

    return templates.TemplateResponse("dashboard/mm_lite.html", {
        "request": request,
        "admin_name": request.session.get("admin_name", "Admin"),
        "page": "mm_lite",
        "record": record,
        "connection": connection,
        "connection_error": connection_error,
        "dashboard_url": meta_app_dashboard_url(),
        "waba_id": settings.whatsapp_business_account_id,
        "phone_number_id": settings.whatsapp_phone_number_id,
    })


@router.get("/callback")
async def legacy_callback(request: Request):
    """Retain old bookmarks without pretending an OAuth code enabled MM API."""
    if not _auth(request):
        return RedirectResponse("/login", status_code=302)
    return RedirectResponse("/mm-lite?notice=manual_setup", status_code=302)


@router.post("/subscribe-webhook")
async def subscribe_webhook(request: Request):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        result = await subscribe_marketing_webhook(settings.whatsapp_business_account_id)
        return JSONResponse({"status": "subscribed", "fields": ["messages"], "result": result})
    except Exception as ex:
        message = _safe_meta_error(ex)
        logger.warning("Marketing Messages webhook subscription failed: %s", message)
        return JSONResponse({"error": message}, status_code=502)


@router.get("/status")
async def mm_lite_status(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    record = await _get_onboarding_record(db)
    try:
        connection = await get_marketing_api_readiness()
        return JSONResponse({
            "api_reachable": True,
            "phone": connection.get("display_phone_number"),
            "quality_rating": connection.get("quality_rating"),
            "routing_verified": bool(record and record.status == "active"),
            "last_verified_at": (
                record.updated_at.isoformat() if record and record.status == "active" else None
            ),
        })
    except Exception as ex:
        return JSONResponse(
            {"api_reachable": False, "error": _safe_meta_error(ex)}, status_code=502
        )


async def mark_marketing_api_verified(payload: dict, db: AsyncSession):
    """Record proof from a status webhook that Meta used marketing_lite."""
    record = await _get_onboarding_record(db)
    if not record:
        record = MMLiteOnboarding(
            waba_id=settings.whatsapp_business_account_id or "unknown",
            status="active",
        )
        db.add(record)
    record.status = "active"
    record.tos_payload = payload
    record.error_message = None
    record.updated_at = datetime.utcnow()
    await db.flush()


async def _get_onboarding_record(db: AsyncSession) -> MMLiteOnboarding | None:
    waba_id = settings.whatsapp_business_account_id
    if not waba_id:
        return None
    return (
        await db.execute(
            select(MMLiteOnboarding).where(MMLiteOnboarding.waba_id == waba_id)
        )
    ).scalar_one_or_none()
