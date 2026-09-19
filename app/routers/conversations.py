from fastapi import APIRouter, Request, Depends, Form, HTTPException, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from sqlalchemy.orm import joinedload
from app.database import get_db
from app.models.contact import Contact
from app.models.conversation import Conversation, Message, MessageDirection, MessageType, MessageStatus
from app.services.whatsapp import whatsapp
from app.services.media_validation import validate_media_upload
from app.services.ai import generate_reply
from datetime import datetime, timedelta
import httpx
from urllib.parse import quote

router = APIRouter(prefix="/conversations", tags=["conversations"])
templates = Jinja2Templates(directory="app/templates")

SERVICE_WINDOW_HOURS = 24


def _within_service_window(conv: Conversation) -> bool:
    """Meta only allows free-form (session) messages within 24h of the customer's last inbound message."""
    if not conv.last_inbound_at:
        return False
    return datetime.utcnow() - conv.last_inbound_at < timedelta(hours=SERVICE_WINDOW_HOURS)


def _auth(request: Request):
    if not request.session.get("admin_email"):
        return None
    return True


@router.get("", response_class=HTMLResponse)
async def conversations_list(
    request: Request,
    page: int = 1,
    status: str = "",
    db: AsyncSession = Depends(get_db),
):
    if not _auth(request):
        return RedirectResponse("/login", status_code=302)

    page = max(1, page)
    per_page = 30
    offset = (page - 1) * per_page

    # Base query with contact eager-loaded
    query = select(Conversation).options(joinedload(Conversation.contact))
    if status in ("open", "closed"):
        query = query.where(Conversation.status == status)
    query = query.order_by(desc(Conversation.last_message_at)).offset(offset).limit(per_page)

    result = await db.execute(query)
    convs = result.unique().scalars().all()

    # Count total for pagination
    count_q = select(func.count(Conversation.id))
    if status in ("open", "closed"):
        count_q = count_q.where(Conversation.status == status)
    total = (await db.execute(count_q)).scalar()
    total_pages = max(1, (total + per_page - 1) // per_page)

    # Batch load last messages
    if convs:
        conv_ids = [c.id for c in convs]
        sub = (
            select(Message.conversation_id, func.max(Message.created_at).label("max_at"))
            .where(Message.conversation_id.in_(conv_ids))
            .group_by(Message.conversation_id)
            .subquery()
        )
        last_msgs_result = await db.execute(
            select(Message).join(
                sub,
                (Message.conversation_id == sub.c.conversation_id) &
                (Message.created_at == sub.c.max_at),
            )
        )
        last_msgs = {m.conversation_id: m for m in last_msgs_result.scalars().all()}
    else:
        last_msgs = {}

    data = [
        {"conv": c, "contact": c.contact, "last_msg": last_msgs.get(c.id)}
        for c in convs
    ]

    return templates.TemplateResponse("dashboard/conversations.html", {
        "request": request,
        "admin_name": request.session.get("admin_name", "Admin"),
        "conversations": data,
        "page": "conversations",
        "current_page": page,
        "total_pages": total_pages,
        "total": total,
        "status_filter": status,
    })


@router.get("/{conv_id}", response_class=HTMLResponse)
async def conversation_detail(conv_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return RedirectResponse("/login", status_code=302)

    conv = (await db.execute(select(Conversation).where(Conversation.id == conv_id))).scalar_one_or_none()
    if not conv:
        raise HTTPException(404, "Conversation not found")

    contact = (await db.execute(select(Contact).where(Contact.id == conv.contact_id))).scalar_one_or_none()
    messages = (await db.execute(
        select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at)
    )).scalars().all()

    return templates.TemplateResponse("dashboard/conversation_detail.html", {
        "request": request,
        "admin_name": request.session.get("admin_name", "Admin"),
        "conv": conv,
        "contact": contact,
        "messages": messages,
        "page": "conversations",
        "within_window": _within_service_window(conv),
    })


@router.post("/{conv_id}/send")
async def send_message(
    conv_id: int,
    request: Request,
    message: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    conv = (await db.execute(select(Conversation).where(Conversation.id == conv_id))).scalar_one_or_none()
    if not conv:
        raise HTTPException(404, "Not found")

    if not _within_service_window(conv):
        return JSONResponse({
            "error": "The 24-hour customer service window has closed for this conversation. "
                     "Meta only allows free-form replies within 24h of the customer's last message — "
                     "send an approved template message instead.",
            "window_closed": True,
        }, status_code=409)

    contact = (await db.execute(select(Contact).where(Contact.id == conv.contact_id))).scalar_one_or_none()
    if not contact or contact.is_blocked:
        return JSONResponse({"error": "Contact is blocked or unavailable"}, status_code=409)

    result = await whatsapp.send_text(contact.phone, message)
    wa_msg_id = result.get("messages", [{}])[0].get("id")

    msg = Message(
        conversation_id=conv_id,
        wa_message_id=wa_msg_id,
        direction=MessageDirection.outbound,
        message_type=MessageType.text,
        content=message,
        status=MessageStatus.sent,
    )
    db.add(msg)
    conv.last_message_at = datetime.utcnow()
    return JSONResponse({"status": "sent", "wa_message_id": wa_msg_id})


@router.post("/{conv_id}/send-media")
async def send_media_message(
    conv_id: int,
    request: Request,
    attachment: UploadFile = File(...),
    caption: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    conv = (await db.execute(select(Conversation).where(Conversation.id == conv_id))).scalar_one_or_none()
    if not conv:
        raise HTTPException(404, "Conversation not found")
    if not _within_service_window(conv):
        return JSONResponse({
            "error": "The 24-hour customer service window has closed. Send an approved media template instead.",
            "window_closed": True,
        }, status_code=409)

    contact = (await db.execute(select(Contact).where(Contact.id == conv.contact_id))).scalar_one_or_none()
    if not contact or contact.is_blocked:
        return JSONResponse({"error": "Contact is blocked or unavailable"}, status_code=409)

    caption = caption.strip()
    if len(caption) > 1024:
        return JSONResponse({"error": "Captions can contain up to 1,024 characters."}, status_code=400)

    try:
        rule, filename, file_size, mime_type = validate_media_upload(
            attachment.file, attachment.filename, attachment.content_type
        )
        if rule.message_type == "audio" and caption:
            return JSONResponse({
                "error": "WhatsApp audio messages do not support captions. Remove the caption and send again."
            }, status_code=400)
        uploaded = await whatsapp.upload_media(
            attachment.file, filename, mime_type
        )
        media_id = uploaded.get("id")
        if not media_id:
            raise RuntimeError("Meta did not return a media ID")
        result = await whatsapp.send_media(
            contact.phone,
            rule.message_type,
            media_id,
            caption=caption,
            filename=filename,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except httpx.HTTPStatusError as exc:
        detail = "Meta rejected the attachment. Check its format and try again."
        try:
            meta_error = exc.response.json().get("error", {}).get("message")
            if meta_error:
                detail = f"Meta rejected the attachment: {meta_error}"
        except (ValueError, AttributeError):
            pass
        return JSONResponse({"error": detail}, status_code=422)
    finally:
        await attachment.close()

    wa_msg_id = result.get("messages", [{}])[0].get("id")
    db.add(Message(
        conversation_id=conv_id,
        wa_message_id=wa_msg_id,
        direction=MessageDirection.outbound,
        message_type=MessageType(rule.message_type),
        content=caption or f"[{rule.message_type}]",
        media_id=media_id,
        caption=caption or None,
        status=MessageStatus.sent,
        raw_payload={
            "filename": filename,
            "mime_type": mime_type,
            "file_size": file_size,
        },
    ))
    conv.last_message_at = datetime.utcnow()
    return JSONResponse({
        "status": "sent",
        "wa_message_id": wa_msg_id,
        "message_type": rule.message_type,
        "filename": filename,
        "caption": caption,
        "file_size": file_size,
    })


@router.get("/media/{message_id}")
async def view_message_media(
    message_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Proxy private Meta media through the authenticated inbox."""
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    message = (await db.execute(select(Message).where(Message.id == message_id))).scalar_one_or_none()
    if not message or not message.media_id:
        raise HTTPException(404, "Media not found")

    try:
        info = await whatsapp.get_media_info(message.media_id)
        media_url = info.get("url")
        if not media_url:
            raise HTTPException(404, "Media is no longer available from Meta")
        content = await whatsapp.download_media(media_url)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(404, "Media is no longer available from Meta") from exc

    raw = message.raw_payload or {}
    nested = raw.get(message.message_type.value, {}) if isinstance(raw, dict) else {}
    filename = raw.get("filename") or nested.get("filename") or f"attachment-{message.id}"
    filename = quote(str(filename).replace("\r", "").replace("\n", ""))
    mime_type = info.get("mime_type") or raw.get("mime_type") or "application/octet-stream"
    disposition = "inline" if message.message_type in {
        MessageType.image, MessageType.video, MessageType.audio, MessageType.sticker
    } else "attachment"
    return Response(
        content=content,
        media_type=mime_type,
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{filename}",
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/{conv_id}/ai-reply")
async def ai_reply(conv_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Generate AI reply using Claude Opus 4.7."""
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    conv = (await db.execute(select(Conversation).where(Conversation.id == conv_id))).scalar_one_or_none()
    if not conv:
        raise HTTPException(404, "Not found")

    if not _within_service_window(conv):
        return JSONResponse({
            "error": "The 24-hour customer service window has closed for this conversation. "
                     "Send an approved template message instead.",
            "window_closed": True,
        }, status_code=409)

    contact = (await db.execute(select(Contact).where(Contact.id == conv.contact_id))).scalar_one_or_none()
    if not contact or contact.is_blocked:
        return JSONResponse({"error": "Contact is blocked or unavailable"}, status_code=409)
    messages = (await db.execute(
        select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at).limit(20)
    )).scalars().all()

    history = [
        {"role": "user" if m.direction == MessageDirection.inbound else "assistant", "content": m.content or ""}
        for m in messages if m.content
    ]

    last_user_msg = next((h["content"] for h in reversed(history) if h["role"] == "user"), "")
    ai_text = await generate_reply(
        user_message=last_user_msg,
        contact_name=contact.profile_name or contact.name or "Customer",
        conversation_history=history[:-1],
    )

    result = await whatsapp.send_text(contact.phone, ai_text)
    wa_msg_id = result.get("messages", [{}])[0].get("id")

    msg = Message(
        conversation_id=conv_id,
        wa_message_id=wa_msg_id,
        direction=MessageDirection.outbound,
        message_type=MessageType.text,
        content=ai_text,
        status=MessageStatus.sent,
        is_ai_reply=True,
    )
    db.add(msg)
    conv.last_message_at = datetime.utcnow()
    return JSONResponse({"status": "sent", "reply": ai_text})


@router.post("/{conv_id}/close")
async def close_conversation(conv_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    conv = (await db.execute(select(Conversation).where(Conversation.id == conv_id))).scalar_one_or_none()
    if conv:
        conv.status = "closed"
    return JSONResponse({"status": "closed"})


@router.post("/{conv_id}/assign")
async def assign_conversation(
    conv_id: int,
    request: Request,
    assignee: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    conv = (await db.execute(select(Conversation).where(Conversation.id == conv_id))).scalar_one_or_none()
    if not conv:
        raise HTTPException(404, "Not found")
    conv.assigned_to = assignee or None
    return JSONResponse({"status": "assigned", "assigned_to": conv.assigned_to})
