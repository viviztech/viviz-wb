from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from app.database import get_db
from app.models.contact import Contact
from app.models.conversation import Conversation, Message, MessageDirection, MessageType, MessageStatus
from app.services.whatsapp import whatsapp
from app.services.ai import generate_reply
from datetime import datetime

router = APIRouter(prefix="/conversations", tags=["conversations"])
templates = Jinja2Templates(directory="app/templates")


def _auth(request: Request):
    if not request.session.get("admin_email"):
        return None
    return True


@router.get("", response_class=HTMLResponse)
async def conversations_list(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return RedirectResponse("/login", status_code=302)

    convs = (await db.execute(
        select(Conversation).order_by(desc(Conversation.last_message_at))
    )).scalars().all()

    data = []
    for conv in convs:
        contact = (await db.execute(select(Contact).where(Contact.id == conv.contact_id))).scalar_one_or_none()
        last_msg = (await db.execute(
            select(Message).where(Message.conversation_id == conv.id).order_by(desc(Message.created_at)).limit(1)
        )).scalar_one_or_none()
        data.append({"conv": conv, "contact": contact, "last_msg": last_msg})

    return templates.TemplateResponse("dashboard/conversations.html", {
        "request": request,
        "admin_name": request.session.get("admin_name", "Admin"),
        "conversations": data,
        "page": "conversations",
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

    contact = (await db.execute(select(Contact).where(Contact.id == conv.contact_id))).scalar_one_or_none()

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


@router.post("/{conv_id}/ai-reply")
async def ai_reply(conv_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Generate AI reply using Claude Opus 4.7."""
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    conv = (await db.execute(select(Conversation).where(Conversation.id == conv_id))).scalar_one_or_none()
    if not conv:
        raise HTTPException(404, "Not found")

    contact = (await db.execute(select(Contact).where(Contact.id == conv.contact_id))).scalar_one_or_none()
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
