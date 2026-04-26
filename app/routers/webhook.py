from fastapi import APIRouter, Request, Response, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.database import get_db
from app.config import settings
from app.models.webhook import WebhookLog
from app.services.message_handler import handle_webhook_payload
import logging

router = APIRouter(prefix="/webhook", tags=["webhook"])
logger = logging.getLogger(__name__)
limiter = Limiter(key_func=get_remote_address)
templates = Jinja2Templates(directory="app/templates")


@router.get("")
async def verify_webhook(request: Request):
    # Meta sends params with dots (hub.mode) which FastAPI can't map to underscored args
    params = request.query_params
    hub_mode = params.get("hub.mode")
    hub_verify_token = params.get("hub.verify_token")
    hub_challenge = params.get("hub.challenge")
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_webhook_verify_token:
        logger.info("Webhook verified successfully")
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("")
@limiter.limit("300/minute")
async def receive_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        payload = await request.json()
        logger.info(f"Webhook received: {payload.get('object', 'unknown')}")
        await handle_webhook_payload(payload, db)
        return {"status": "ok"}
    except Exception as ex:
        logger.exception(f"Webhook processing error: {ex}")
        return {"status": "ok"}


@router.get("/logs", response_class=HTMLResponse)
async def webhook_logs_page(
    request: Request,
    page: int = 1,
    event_type: str = "",
    db: AsyncSession = Depends(get_db),
):
    if not request.session.get("admin_email"):
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/login", status_code=302)

    from sqlalchemy import func
    per_page = 50
    offset = (max(1, page) - 1) * per_page

    query = select(WebhookLog).order_by(desc(WebhookLog.created_at))
    count_q = select(func.count(WebhookLog.id))
    if event_type:
        query = query.where(WebhookLog.event_type == event_type)
        count_q = count_q.where(WebhookLog.event_type == event_type)

    total = (await db.execute(count_q)).scalar()
    total_pages = max(1, (total + per_page - 1) // per_page)
    logs = (await db.execute(query.offset(offset).limit(per_page))).scalars().all()

    # Distinct event types for filter dropdown
    types_result = await db.execute(
        select(WebhookLog.event_type).distinct().order_by(WebhookLog.event_type)
    )
    event_types = [r[0] for r in types_result.fetchall() if r[0]]

    return templates.TemplateResponse("dashboard/webhook_logs.html", {
        "request": request,
        "admin_name": request.session.get("admin_name", "Admin"),
        "logs": logs,
        "page": "webhook_logs",
        "current_page": page,
        "total_pages": total_pages,
        "total": total,
        "event_type_filter": event_type,
        "event_types": event_types,
    })


@router.post("/logs/{log_id}/replay")
async def replay_webhook(log_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Re-process a stored webhook payload."""
    if not request.session.get("admin_email"):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    log = (await db.execute(select(WebhookLog).where(WebhookLog.id == log_id))).scalar_one_or_none()
    if not log:
        return JSONResponse({"error": "Log not found"}, status_code=404)
    if not log.payload:
        return JSONResponse({"error": "No payload to replay"}, status_code=400)

    try:
        await handle_webhook_payload(log.payload, db)
        log.processed = "replayed"
        await db.commit()
        return JSONResponse({"status": "replayed"})
    except Exception as ex:
        logger.error(f"Replay failed for log {log_id}: {ex}")
        return JSONResponse({"error": str(ex)}, status_code=500)
