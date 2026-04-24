from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from sqlalchemy.orm import joinedload
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
