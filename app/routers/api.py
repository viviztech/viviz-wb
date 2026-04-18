"""REST API endpoints for external integrations."""
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from app.database import get_db
from app.services.whatsapp import whatsapp
from app.models.contact import Contact
from app.models.conversation import Conversation, Message, MessageDirection, MessageType, MessageStatus
from app.config import settings
from datetime import datetime

router = APIRouter(prefix="/api/v1", tags=["api"])


class SendTextRequest(BaseModel):
    to: str
    message: str


class SendTemplateRequest(BaseModel):
    to: str
    template_name: str
    language: str = "en"
    components: Optional[list] = None


def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != settings.secret_key:
        raise HTTPException(401, "Invalid API key")
    return x_api_key


@router.post("/send/text")
async def api_send_text(
    req: SendTextRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    result = await whatsapp.send_text(req.to, req.message)
    wa_msg_id = result.get("messages", [{}])[0].get("id")

    contact_res = await db.execute(select(Contact).where(Contact.phone == req.to))
    contact = contact_res.scalar_one_or_none()
    if not contact:
        contact = Contact(phone=req.to, wa_id=req.to)
        db.add(contact)
        await db.flush()

    conv_res = await db.execute(
        select(Conversation).where(Conversation.contact_id == contact.id, Conversation.status == "open")
    )
    conv = conv_res.scalar_one_or_none()
    if not conv:
        conv = Conversation(contact_id=contact.id, status="open")
        db.add(conv)
        await db.flush()

    msg = Message(
        conversation_id=conv.id,
        wa_message_id=wa_msg_id,
        direction=MessageDirection.outbound,
        message_type=MessageType.text,
        content=req.message,
        status=MessageStatus.sent,
    )
    db.add(msg)
    conv.last_message_at = datetime.utcnow()
    return {"status": "sent", "wa_message_id": wa_msg_id}


@router.post("/send/template")
async def api_send_template(
    req: SendTemplateRequest,
    _: str = Depends(verify_api_key),
):
    result = await whatsapp.send_template(req.to, req.template_name, req.language, req.components)
    return {"status": "sent", "result": result}


@router.get("/contacts")
async def api_contacts(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    contacts = (await db.execute(select(Contact))).scalars().all()
    return [{"id": c.id, "phone": c.phone, "name": c.name or c.profile_name, "tags": c.tags} for c in contacts]


@router.get("/health")
async def health():
    return {"status": "ok", "service": "Viviz WhatsApp Business API"}
