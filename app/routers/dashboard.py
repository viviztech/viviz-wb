from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from datetime import datetime, timedelta
from app.database import get_db
from app.models.contact import Contact
from app.models.conversation import Conversation, Message, MessageDirection
from app.models.broadcast import Broadcast
from app.services.auth import get_session

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


def auth_check(request: Request):
    if not request.session.get("admin_email"):
        return None
    return request.session.get("admin_email")


@router.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return RedirectResponse("/dashboard", status_code=302)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    if not auth_check(request):
        return RedirectResponse("/login", status_code=302)

    since = datetime.utcnow() - timedelta(days=30)

    total_contacts = (await db.execute(select(func.count(Contact.id)))).scalar()
    total_conversations = (await db.execute(select(func.count(Conversation.id)))).scalar()
    open_conversations = (await db.execute(
        select(func.count(Conversation.id)).where(Conversation.status == "open")
    )).scalar()
    messages_today = (await db.execute(
        select(func.count(Message.id)).where(Message.created_at >= datetime.utcnow().replace(hour=0, minute=0, second=0))
    )).scalar()
    inbound_today = (await db.execute(
        select(func.count(Message.id)).where(
            Message.created_at >= datetime.utcnow().replace(hour=0, minute=0, second=0),
            Message.direction == MessageDirection.inbound,
        )
    )).scalar()

    recent_conversations = (await db.execute(
        select(Conversation).order_by(desc(Conversation.last_message_at)).limit(10)
    )).scalars().all()

    # Load contacts for recent conversations
    conv_data = []
    for conv in recent_conversations:
        contact = (await db.execute(select(Contact).where(Contact.id == conv.contact_id))).scalar_one_or_none()
        last_msg = (await db.execute(
            select(Message).where(Message.conversation_id == conv.id).order_by(desc(Message.created_at)).limit(1)
        )).scalar_one_or_none()
        conv_data.append({"conv": conv, "contact": contact, "last_msg": last_msg})

    return templates.TemplateResponse("dashboard/index.html", {
        "request": request,
        "admin_name": request.session.get("admin_name", "Admin"),
        "total_contacts": total_contacts,
        "total_conversations": total_conversations,
        "open_conversations": open_conversations,
        "messages_today": messages_today,
        "inbound_today": inbound_today,
        "recent_conversations": conv_data,
        "page": "dashboard",
    })
