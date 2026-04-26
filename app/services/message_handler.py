from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.contact import Contact
from app.models.conversation import Conversation, Message, MessageDirection, MessageType, MessageStatus
from app.models.webhook import WebhookLog
from app.services.whatsapp import whatsapp
from app.services.media import upload_media_to_s3
import logging

logger = logging.getLogger(__name__)


async def handle_webhook_payload(payload: dict, db: AsyncSession):
    """Process incoming WhatsApp webhook payload."""
    try:
        entry = payload.get("entry", [])
        for e in entry:
            for change in e.get("changes", []):
                field = change.get("field", "")
                value = change.get("value", {})

                if field == "marketing_messages":
                    await _process_marketing_messages_field(value, db)
                else:
                    await _process_value(value, db)
    except Exception as ex:
        logger.error(f"Webhook processing error: {ex}")
        log = WebhookLog(payload=payload, processed="error", error=str(ex))
        db.add(log)


async def _process_marketing_messages_field(value: dict, db: AsyncSession):
    """
    Handle events delivered under the `marketing_messages` webhook field.
    Covers:
    - tos_signed: business accepted MM Lite Terms of Service
    - message_deliveries / message_reads: MM Lite delivery metrics
    - message_errors: MM Lite send failures
    """
    event_type = value.get("event")

    if event_type == "tos_signed":
        from app.routers.mm_lite import handle_tos_signed_event
        await handle_tos_signed_event(value, db)
        db.add(WebhookLog(event_type="mm_lite_tos_signed", payload=value))
        logger.info("MM Lite ToS signed event processed")
        return

    # Delivery / read / error metrics from MM Lite
    if event_type in ("message_deliveries", "message_reads", "message_errors"):
        db.add(WebhookLog(event_type=f"mm_lite_{event_type}", payload=value))
        logger.debug(f"MM Lite event logged: {event_type}")
        return

    # Fallback: log unknown marketing_messages events
    db.add(WebhookLog(event_type="mm_lite_unknown", payload=value))
    logger.debug(f"Unknown marketing_messages event: {event_type}")


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

    # Upload media to S3 if present
    media_url = None
    if media_id and msg_type in ("image", "video", "audio", "document", "sticker"):
        try:
            content_type_map = {
                "image": "image/jpeg", "video": "video/mp4",
                "audio": "audio/ogg", "document": "application/pdf", "sticker": "image/webp",
            }
            raw_url = await whatsapp.get_media_url(media_id)
            if raw_url:
                media_bytes = await whatsapp.download_media(raw_url)
                media_url = await upload_media_to_s3(
                    media_bytes, media_id,
                    content_type=content_type_map.get(msg_type, "application/octet-stream"),
                )
        except Exception as ex:
            logger.warning(f"Media upload failed for {media_id}: {ex}")

    message = Message(
        conversation_id=conversation.id,
        wa_message_id=wa_message_id,
        direction=MessageDirection.inbound,
        message_type=MessageType(msg_type) if msg_type in MessageType.__members__ else MessageType.text,
        content=content,
        media_id=media_id,
        media_url=media_url,
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

    # Opt-out / unsubscribe handling — must run before auto-replies
    if content and msg_type == "text":
        opted_out = await _check_optout(content, contact, from_phone, db)
        if not opted_out:
            await _check_auto_reply(content, from_phone, conversation.id, db)

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
    from app.models.broadcast import BroadcastRecipient

    wa_message_id = status.get("id", "")
    new_status = status.get("status", "")

    status_map = {
        "sent": MessageStatus.sent,
        "delivered": MessageStatus.delivered,
        "read": MessageStatus.read,
        "failed": MessageStatus.failed,
    }

    # Update message status
    result = await db.execute(select(Message).where(Message.wa_message_id == wa_message_id))
    message = result.scalar_one_or_none()
    if message and new_status in status_map:
        message.status = status_map[new_status]
        if new_status == "failed":
            errors = status.get("errors", [])
            message.error_message = errors[0].get("message") if errors else "Unknown error"

    # Update broadcast recipient delivery stats
    recipient_result = await db.execute(
        select(BroadcastRecipient).where(BroadcastRecipient.wa_message_id == wa_message_id)
    )
    recipient = recipient_result.scalar_one_or_none()
    if recipient:
        now = datetime.utcnow()
        from app.models.broadcast import Broadcast
        from sqlalchemy import update
        if new_status == "delivered" and not recipient.delivered_at:
            recipient.delivered_at = now
            recipient.status = "delivered"
            await db.execute(
                update(Broadcast)
                .where(Broadcast.id == recipient.broadcast_id)
                .values(delivered_count=Broadcast.delivered_count + 1)
            )
            logger.info(f"Broadcast recipient {wa_message_id} marked delivered")
        elif new_status == "read" and not recipient.read_at:
            recipient.read_at = now
            recipient.status = "read"
            await db.execute(
                update(Broadcast)
                .where(Broadcast.id == recipient.broadcast_id)
                .values(read_count=Broadcast.read_count + 1)
            )
            logger.info(f"Broadcast recipient {wa_message_id} marked read")
        elif new_status == "failed" and recipient.status not in ("delivered", "read"):
            recipient.status = "failed"
            errors = status.get("errors", [])
            recipient.error_message = (errors[0].get("message") if errors else "Unknown error")[:500]
            await db.execute(
                update(Broadcast)
                .where(Broadcast.id == recipient.broadcast_id)
                .values(failed_count=Broadcast.failed_count + 1)
            )
            logger.info(f"Broadcast recipient {wa_message_id} marked failed")

    db.add(WebhookLog(
        event_type=f"status_{new_status}",
        wa_message_id=wa_message_id,
        payload=status,
    ))


_OPT_OUT_KEYWORDS = {"stop", "unsubscribe", "optout", "opt out", "opt-out", "cancel", "remove me", "no more"}
_OPT_IN_KEYWORDS = {"start", "subscribe", "optin", "opt in", "opt-in", "yes"}


async def _check_optout(text: str, contact: Contact, to_phone: str, db: AsyncSession) -> bool:
    """
    Handle STOP / UNSUBSCRIBE keywords to opt contacts out.
    Handle START / SUBSCRIBE to re-opt them in.
    Returns True if the message was an opt-out/in command (suppresses auto-reply).
    """
    lower = text.strip().lower()

    if lower in _OPT_OUT_KEYWORDS:
        if contact.is_opted_in:
            contact.is_opted_in = False
            logger.info(f"Contact {to_phone} opted out via keyword: {text!r}")
            try:
                await whatsapp.send_text(
                    to_phone,
                    "You have been unsubscribed from our messages. "
                    "Reply START anytime to subscribe again.",
                )
            except Exception as ex:
                logger.warning(f"Could not send opt-out confirmation to {to_phone}: {ex}")
        return True

    if lower in _OPT_IN_KEYWORDS:
        if not contact.is_opted_in:
            contact.is_opted_in = True
            logger.info(f"Contact {to_phone} opted in via keyword: {text!r}")
            try:
                await whatsapp.send_text(
                    to_phone,
                    "You have been subscribed to our messages. "
                    "Reply STOP anytime to unsubscribe.",
                )
            except Exception as ex:
                logger.warning(f"Could not send opt-in confirmation to {to_phone}: {ex}")
        return True

    return False


async def _check_auto_reply(text: str, to_phone: str, conversation_id: int, db: AsyncSession):
    """Match incoming text against active auto-reply rules and fire the first match."""
    from app.models.auto_reply import AutoReply
    from sqlalchemy import update

    rules = (await db.execute(
        select(AutoReply)
        .where(AutoReply.is_active == True)
        .order_by(AutoReply.priority.desc(), AutoReply.id)
    )).scalars().all()

    lower_text = text.strip().lower()
    for rule in rules:
        kw = rule.keyword.lower()
        if rule.match_type == "exact" and lower_text != kw:
            continue
        elif rule.match_type == "starts_with" and not lower_text.startswith(kw):
            continue
        elif rule.match_type == "contains" and kw not in lower_text:
            continue

        # Fire the rule
        try:
            if rule.template_name:
                result = await whatsapp.send_template(to_phone, rule.template_name)
                wa_msg_id = result.get("messages", [{}])[0].get("id")
                reply_content = f"[template: {rule.template_name}]"
            else:
                result = await whatsapp.send_text(to_phone, rule.reply_text)
                wa_msg_id = result.get("messages", [{}])[0].get("id")
                reply_content = rule.reply_text

            db.add(Message(
                conversation_id=conversation_id,
                wa_message_id=wa_msg_id,
                direction=MessageDirection.outbound,
                message_type=MessageType.text,
                content=reply_content,
                status=MessageStatus.sent,
            ))

            # Increment trigger count
            await db.execute(
                update(AutoReply)
                .where(AutoReply.id == rule.id)
                .values(trigger_count=AutoReply.trigger_count + 1)
            )
            logger.info(f"Auto-reply rule '{rule.keyword}' fired for {to_phone}")
        except Exception as ex:
            logger.error(f"Auto-reply failed for rule {rule.id}: {ex}")
        break  # only fire the first matching rule
