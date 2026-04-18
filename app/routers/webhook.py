from fastapi import APIRouter, Request, Response, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.config import settings
from app.services.message_handler import handle_webhook_payload
import logging

router = APIRouter(prefix="/webhook", tags=["webhook"])
logger = logging.getLogger(__name__)


@router.get("")
async def verify_webhook(
    hub_mode: str | None = None,
    hub_challenge: str | None = None,
    hub_verify_token: str | None = None,
):
    """Meta webhook verification challenge."""
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_webhook_verify_token:
        logger.info("Webhook verified successfully")
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("")
async def receive_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Receive WhatsApp webhook events from Meta."""
    try:
        payload = await request.json()
        logger.info(f"Webhook received: {payload.get('object', 'unknown')}")
        await handle_webhook_payload(payload, db)
        return {"status": "ok"}
    except Exception as ex:
        logger.error(f"Webhook error: {ex}")
        # Always return 200 to Meta to prevent retries
        return {"status": "ok"}
