from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.contact import Contact
from app.models.conversation import Conversation, Message, MessageDirection, MessageType, MessageStatus
from app.models.webhook import WebhookLog
from app.services.whatsapp import whatsapp
import logging

logger = logging.getLogger(__name__)


async def handle_webhook_payload(payload: dict, db: AsyncSession):
    """Process incoming WhatsApp webhook payload."""
    try:
        entry = payload.get("entry", [])
        for e in entry:
            for change in e.get("changes", []):
                value = change.get("value", {})
                await _process_value(value, db)
    except Exception as ex:
        logger.error(f"Webhook processing error: {ex}")
        log = WebhookLog(payload=payload, processed="error", error=str(ex))
        db.add(log)


async def _process_value(value: dict, db: AsyncSession):
    messages = value.get("messages", [])
    statuses = value.get("statuses", [])
    contacts_meta = value.get("contacts", [])

    contact_map = {c["wa_id"]: c.get("profile", {}).get("name", "") for c in contacts_meta}

    for msg in messages:
        await _handle_incoming_message(msg, contact_map, db)

    for status in statuses:
        await _handle_status_update(status, db)


async def _handle_incoming_message(msg: dict, contact_map: dict, db: AsyncSession):
    from_phone = msg.get("from", "")
    wa_message_id = msg.get("id", "")
    msg_type = msg.get("type", "text")
    timestamp = msg.get("timestamp")
    profile_name = contact_map.get(from_phone, "")

    # Upsert contact
    result = await db.execute(select(Contact).where(Contact.phone == from_phone))
    contact = result.scalar_one_or_none()
    if not contact:
        contact = Contact(phone=from_phone, wa_id=from_phone, profile_name=profile_name)
        db.add(contact)
        await db.flush()
    else:
        contact.last_seen = datetime.utcnow()
        if profile_name and not contact.profile_name:
            contact.profile_name = profile_name

    # Get or create conversation
    result = await db.execute(
        select(Conversation).where(Conversation.contact_id == contact.id, Conversation.status == "open")
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        conversation = Conversation(contact_id=contact.id, status="open")
        db.add(conversation)
        await db.flush()

    conversation.last_message_at = datetime.utcnow()

    # Extract content
    content, media_id, caption = _extract_message_content(msg, msg_type)

    message = Message(
        conversation_id=conversation.id,
        wa_message_id=wa_message_id,
        direction=MessageDirection.inbound,
        message_type=MessageType(msg_type) if msg_type in MessageType.__members__ else MessageType.text,
        content=content,
        media_id=media_id,
        caption=caption,
        status=MessageStatus.delivered,
        raw_payload=msg,
    )
    db.add(message)

    # Mark as read
    try:
        await whatsapp.mark_read(wa_message_id)
    except Exception as ex:
        logger.warning(f"Could not mark read: {ex}")

    # Log webhook
    db.add(WebhookLog(
        event_type="message",
        wa_message_id=wa_message_id,
        from_phone=from_phone,
        payload=msg,
    ))


def _extract_message_content(msg: dict, msg_type: str) -> tuple[str, str | None, str | None]:
    content = ""
    media_id = None
    caption = None

    if msg_type == "text":
        content = msg.get("text", {}).get("body", "")
    elif msg_type in ("image", "video", "audio", "document", "sticker"):
        media_data = msg.get(msg_type, {})
        media_id = media_data.get("id")
        caption = media_data.get("caption", "")
        content = caption or f"[{msg_type}]"
    elif msg_type == "location":
        loc = msg.get("location", {})
        content = f"Location: {loc.get('latitude')}, {loc.get('longitude')}"
    elif msg_type == "interactive":
        interactive = msg.get("interactive", {})
        if interactive.get("type") == "button_reply":
            content = interactive.get("button_reply", {}).get("title", "")
        elif interactive.get("type") == "list_reply":
            content = interactive.get("list_reply", {}).get("title", "")
    elif msg_type == "button":
        content = msg.get("button", {}).get("text", "")

    return content, media_id, caption


async def _handle_status_update(status: dict, db: AsyncSession):
    wa_message_id = status.get("id", "")
    new_status = status.get("status", "")

    status_map = {
        "sent": MessageStatus.sent,
        "delivered": MessageStatus.delivered,
        "read": MessageStatus.read,
        "failed": MessageStatus.failed,
    }

    result = await db.execute(select(Message).where(Message.wa_message_id == wa_message_id))
    message = result.scalar_one_or_none()
    if message and new_status in status_map:
        message.status = status_map[new_status]
        if new_status == "failed":
            errors = status.get("errors", [])
            message.error_message = errors[0].get("message") if errors else "Unknown error"

    db.add(WebhookLog(
        event_type=f"status_{new_status}",
        wa_message_id=wa_message_id,
        payload=status,
    ))
