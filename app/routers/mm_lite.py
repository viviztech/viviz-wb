from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
import logging

from app.database import get_db
from app.config import settings
from app.models.mm_lite import MMLiteOnboarding
from app.services.mm_lite import (
    build_embedded_signup_url,
    get_waba_mm_lite_status,
    subscribe_mm_lite_webhook,
)

router = APIRouter(prefix="/mm-lite", tags=["mm_lite"])
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)


def _auth(request: Request):
    return request.session.get("admin_email")


@router.get("", response_class=HTMLResponse)
async def mm_lite_page(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return RedirectResponse("/login", status_code=302)

    record = await _get_onboarding_record(db)

    # Try to refresh status from Meta if we think we're active
    meta_status = None
    if settings.whatsapp_business_account_id:
        try:
            data = await get_waba_mm_lite_status(settings.whatsapp_business_account_id)
            meta_status = data.get("marketing_messages_lite_status")
            # Sync DB if Meta says active
            if meta_status == "ACTIVE" and record and record.status != "active":
                record.status = "active"
                if not record.tos_accepted_at:
                    record.tos_accepted_at = datetime.utcnow()
                await db.commit()
        except Exception as ex:
            logger.warning(f"MM Lite status check failed: {ex}")

    onboard_url = build_embedded_signup_url(
        redirect_uri=f"{settings.app_url}/mm-lite/callback"
    )

    return templates.TemplateResponse("dashboard/mm_lite.html", {
        "request": request,
        "admin_name": request.session.get("admin_name", "Admin"),
        "page": "mm_lite",
        "record": record,
        "meta_status": meta_status,
        "onboard_url": onboard_url,
        "waba_id": settings.whatsapp_business_account_id,
    })


@router.get("/callback")
async def mm_lite_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Embedded Signup OAuth callback. After the business owner completes the
    MM Lite ToS flow on Facebook, Meta redirects here with a `code`.
    We create/update the onboarding record and redirect to the MM Lite page.
    Meta will also fire a `tos_signed` webhook event asynchronously.
    """
    if not _auth(request):
        return RedirectResponse("/login", status_code=302)

    if error:
        logger.warning(f"MM Lite Embedded Signup error: {error}")
        return RedirectResponse("/mm-lite?error=signup_cancelled", status_code=302)

    waba_id = settings.whatsapp_business_account_id
    record = await _get_onboarding_record(db)

    if not record:
        record = MMLiteOnboarding(waba_id=waba_id, status="pending")
        db.add(record)

    # Mark pending — will become active when tos_signed webhook arrives
    record.status = "pending"
    await db.commit()

    # Try subscribing webhook fields immediately (best-effort)
    try:
        await subscribe_mm_lite_webhook(waba_id)
        logger.info(f"MM Lite webhook subscribed for WABA {waba_id}")
    except Exception as ex:
        logger.warning(f"MM Lite webhook subscription failed: {ex}")

    return RedirectResponse("/mm-lite?signup=complete", status_code=302)


@router.post("/subscribe-webhook")
async def subscribe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Manually trigger webhook field subscription for this WABA."""
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    waba_id = settings.whatsapp_business_account_id
    if not waba_id:
        return JSONResponse({"error": "WABA ID not configured"}, status_code=400)

    try:
        result = await subscribe_mm_lite_webhook(waba_id)
        return JSONResponse({"status": "subscribed", "result": result})
    except Exception as ex:
        return JSONResponse({"error": str(ex)}, status_code=500)


@router.get("/status")
async def mm_lite_status(request: Request, db: AsyncSession = Depends(get_db)):
    """JSON status endpoint — used by the UI to poll current state."""
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    record = await _get_onboarding_record(db)
    meta_status = None
    if settings.whatsapp_business_account_id:
        try:
            data = await get_waba_mm_lite_status(settings.whatsapp_business_account_id)
            meta_status = data.get("marketing_messages_lite_status")
        except Exception:
            pass

    return JSONResponse({
        "db_status": record.status if record else "not_started",
        "meta_status": meta_status,
        "tos_accepted_at": record.tos_accepted_at.isoformat() if record and record.tos_accepted_at else None,
        "waba_id": settings.whatsapp_business_account_id,
    })


async def handle_tos_signed_event(payload: dict, db: AsyncSession):
    """
    Called by the webhook handler when Meta fires a `tos_signed` event under
    the `marketing_messages` field. Marks onboarding as complete in the DB.
    """
    waba_id = (
        payload.get("waba_id")
        or payload.get("whatsapp_business_account_id")
        or settings.whatsapp_business_account_id
    )
    record = await _get_onboarding_record(db)

    if not record:
        record = MMLiteOnboarding(waba_id=waba_id)
        db.add(record)

    record.status = "active"
    record.tos_accepted_at = datetime.utcnow()
    record.tos_payload = payload
    record.error_message = None
    await db.commit()
    logger.info(f"MM Lite ToS accepted for WABA {waba_id}")

    # Subscribe webhook fields now that ToS is accepted
    try:
        await subscribe_mm_lite_webhook(waba_id)
    except Exception as ex:
        logger.warning(f"Post-tos webhook subscription failed: {ex}")


async def _get_onboarding_record(db: AsyncSession) -> MMLiteOnboarding | None:
    waba_id = settings.whatsapp_business_account_id
    if not waba_id:
        return None
    return (
        await db.execute(
            select(MMLiteOnboarding).where(MMLiteOnboarding.waba_id == waba_id)
        )
    ).scalar_one_or_none()
