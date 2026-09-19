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
from app.models.template import MessageTemplate
from app.services.consent import (
    has_active_consent,
    marketing_frequency_allowed,
    template_has_optout,
    validate_business_messaging_configuration,
)
from app.config import settings
from datetime import datetime, timedelta

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
    if not settings.api_key or x_api_key != settings.api_key:
        raise HTTPException(401, "Invalid API key")
    return x_api_key


@router.post("/send/text")
async def api_send_text(
    req: SendTextRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    contact_res = await db.execute(select(Contact).where(Contact.phone == req.to))
    contact = contact_res.scalar_one_or_none()
    if not contact or contact.is_blocked:
        raise HTTPException(409, "Contact is unknown or blocked")

    conv_res = await db.execute(
        select(Conversation).where(Conversation.contact_id == contact.id, Conversation.status == "open")
    )
    conv = conv_res.scalar_one_or_none()
    if not conv or not conv.last_inbound_at or datetime.utcnow() - conv.last_inbound_at >= timedelta(hours=24):
        raise HTTPException(409, "Free-form text is allowed only within 24 hours of the customer's last message")

    result = await whatsapp.send_text(req.to, req.message)
    wa_msg_id = result.get("messages", [{}])[0].get("id")

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
    db: AsyncSession = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    try:
        validate_business_messaging_configuration()
    except ValueError as ex:
        raise HTTPException(409, str(ex)) from ex
    contact = (await db.execute(select(Contact).where(Contact.phone == req.to))).scalar_one_or_none()
    if not contact or contact.is_blocked:
        raise HTTPException(409, "Contact is unknown or blocked")
    template = (await db.execute(
        select(MessageTemplate).where(MessageTemplate.name == req.template_name)
    )).scalar_one_or_none()
    if not template or template.status != "APPROVED" or not template.is_active:
        raise HTTPException(409, "Template is not approved and active")
    if template.language != req.language:
        raise HTTPException(409, "Template language mismatch")
    category = (template.category or "").lower()
    if category not in {"marketing", "utility", "authentication"}:
        raise HTTPException(409, "Unsupported template category")
    if not await has_active_consent(db, contact.id, category):
        raise HTTPException(409, f"No active {category} consent for this contact")
    if category == "marketing":
        if not template_has_optout(template):
            raise HTTPException(409, "Marketing template lacks opt-out instructions")
        if not await marketing_frequency_allowed(db, contact.id):
            raise HTTPException(429, "Marketing frequency cap reached for this contact")
    result = await whatsapp.send_template(req.to, req.template_name, req.language, req.components)
    wa_msg_id = result.get("messages", [{}])[0].get("id")
    conv = (await db.execute(
        select(Conversation).where(Conversation.contact_id == contact.id, Conversation.status == "open")
    )).scalar_one_or_none()
    if not conv:
        conv = Conversation(contact_id=contact.id, status="open")
        db.add(conv)
        await db.flush()
    db.add(Message(
        conversation_id=conv.id,
        wa_message_id=wa_msg_id,
        direction=MessageDirection.outbound,
        message_type=MessageType.template,
        content=f"[template: {req.template_name}]",
        template_name=req.template_name,
        status=MessageStatus.sent,
    ))
    conv.last_message_at = datetime.utcnow()
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
