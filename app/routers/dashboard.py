from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from sqlalchemy.orm import joinedload, selectinload
from datetime import datetime, timedelta
from app.database import get_db
from app.models.contact import Contact
from app.models.conversation import Conversation, Message, MessageDirection
from app.services.auth import get_session

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")

_stats_cache: dict = {}
_CACHE_TTL = 60  # seconds


def _auth(request: Request):
    if not request.session.get("admin_email"):
        return None
    return request.session.get("admin_email")


@router.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return RedirectResponse("/dashboard", status_code=302)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return RedirectResponse("/login", status_code=302)

    now = datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Serve cached stats if fresh
    cached = _stats_cache.get("stats")
    if cached and (now - cached["ts"]).total_seconds() < _CACHE_TTL:
        stats = cached
    else:
        # Sequential queries — asyncio.gather on the same session causes IllegalStateChangeError
        total_contacts = (await db.execute(select(func.count(Contact.id)))).scalar()
        total_conversations = (await db.execute(select(func.count(Conversation.id)))).scalar()
        open_conversations = (await db.execute(
            select(func.count(Conversation.id)).where(Conversation.status == "open")
        )).scalar()
        messages_today = (await db.execute(
            select(func.count(Message.id)).where(Message.created_at >= today)
        )).scalar()
        inbound_today = (await db.execute(
            select(func.count(Message.id)).where(
                Message.created_at >= today,
                Message.direction == MessageDirection.inbound,
            )
        )).scalar()
        stats = {
            "ts": now,
            "total_contacts": total_contacts,
            "total_conversations": total_conversations,
            "open_conversations": open_conversations,
            "messages_today": messages_today,
            "inbound_today": inbound_today,
        }
        _stats_cache["stats"] = stats

    # Recent conversations — single query with contact via joinedload
    result = await db.execute(
        select(Conversation)
        .options(joinedload(Conversation.contact))
        .order_by(desc(Conversation.last_message_at))
        .limit(10)
    )
    recent_convs = result.unique().scalars().all()

    # Batch load last message per conversation in one query
    if recent_convs:
        conv_ids = [c.id for c in recent_convs]
        # Subquery: max created_at per conversation
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

    conv_data = [
        {"conv": c, "contact": c.contact, "last_msg": last_msgs.get(c.id)}
        for c in recent_convs
    ]

    return templates.TemplateResponse("dashboard/index.html", {
        "request": request,
        "admin_name": request.session.get("admin_name", "Admin"),
        "total_contacts": stats["total_contacts"],
        "total_conversations": stats["total_conversations"],
        "open_conversations": stats["open_conversations"],
        "messages_today": stats["messages_today"],
        "inbound_today": stats["inbound_today"],
        "recent_conversations": conv_data,
        "page": "dashboard",
    })
