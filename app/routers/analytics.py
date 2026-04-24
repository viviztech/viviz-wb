from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, and_, case, Integer
from datetime import datetime, timedelta
from app.database import get_db
from app.models.contact import Contact
from app.models.conversation import Conversation, Message, MessageDirection
from app.models.broadcast import Broadcast, BroadcastRecipient
from app.models.template import MessageTemplate

router = APIRouter(prefix="/analytics", tags=["analytics"])
templates = Jinja2Templates(directory="app/templates")


def _auth(request: Request):
    return request.session.get("admin_email")


@router.get("", response_class=HTMLResponse)
async def analytics_page(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse("dashboard/analytics.html", {
        "request": request,
        "admin_name": request.session.get("admin_name", "Admin"),
        "page": "analytics",
    })


@router.get("/data", response_class=JSONResponse)
async def analytics_data(request: Request, days: int = 30, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    days = min(max(days, 7), 90)
    since = datetime.utcnow() - timedelta(days=days)

    # --- Message volume per day (inbound + outbound) ---
    msg_by_day_q = await db.execute(
        select(
            func.date(Message.created_at).label("day"),
            func.sum(case((Message.direction == MessageDirection.inbound, 1), else_=0)).label("inbound"),
            func.sum(case((Message.direction == MessageDirection.outbound, 1), else_=0)).label("outbound"),
        )
        .where(Message.created_at >= since)
        .group_by(func.date(Message.created_at))
        .order_by(func.date(Message.created_at))
    )
    msg_by_day = msg_by_day_q.fetchall()

    # Fill all days with 0 for missing dates
    day_map: dict = {}
    for i in range(days):
        d = (since + timedelta(days=i)).strftime("%Y-%m-%d")
        day_map[d] = {"inbound": 0, "outbound": 0}
    for row in msg_by_day:
        d = str(row.day)
        day_map[d] = {"inbound": int(row.inbound or 0), "outbound": int(row.outbound or 0)}

    # --- Broadcast stats ---
    bc_result = await db.execute(
        select(
            Broadcast.status,
            func.count(Broadcast.id).label("count"),
            func.sum(Broadcast.total_count).label("total_recipients"),
            func.sum(Broadcast.sent_count).label("sent"),
            func.sum(Broadcast.delivered_count).label("delivered"),
            func.sum(Broadcast.failed_count).label("failed"),
        )
        .where(Broadcast.created_at >= since)
        .group_by(Broadcast.status)
    )
    bc_rows = bc_result.fetchall()
    broadcast_summary = {
        "total": sum(r.count for r in bc_rows),
        "total_recipients": int(sum((r.total_recipients or 0) for r in bc_rows)),
        "sent": int(sum((r.sent or 0) for r in bc_rows)),
        "delivered": int(sum((r.delivered or 0) for r in bc_rows)),
        "failed": int(sum((r.failed or 0) for r in bc_rows)),
    }
    broadcast_summary["delivery_rate"] = round(
        (broadcast_summary["delivered"] / broadcast_summary["sent"] * 100) if broadcast_summary["sent"] else 0, 1
    )

    # --- Template performance (top 5 by usage in broadcasts) ---
    tpl_result = await db.execute(
        select(
            Broadcast.template_name,
            func.count(Broadcast.id).label("broadcast_count"),
            func.sum(Broadcast.sent_count).label("sent"),
            func.sum(Broadcast.delivered_count).label("delivered"),
        )
        .where(Broadcast.created_at >= since, Broadcast.status == "completed")
        .group_by(Broadcast.template_name)
        .order_by(desc(func.sum(Broadcast.sent_count)))
        .limit(5)
    )
    template_perf = [
        {
            "name": r.template_name,
            "broadcasts": int(r.broadcast_count),
            "sent": int(r.sent or 0),
            "delivered": int(r.delivered or 0),
            "delivery_rate": round((r.delivered or 0) / (r.sent or 1) * 100, 1),
        }
        for r in tpl_result.fetchall()
    ]

    # --- Contact growth per day ---
    contact_by_day_q = await db.execute(
        select(
            func.date(Contact.created_at).label("day"),
            func.count(Contact.id).label("count"),
        )
        .where(Contact.created_at >= since)
        .group_by(func.date(Contact.created_at))
        .order_by(func.date(Contact.created_at))
    )
    contact_map = {str(r.day): int(r.count) for r in contact_by_day_q.fetchall()}

    # --- Summary totals ---
    total_contacts = await db.execute(select(func.count(Contact.id)))
    total_messages = await db.execute(select(func.count(Message.id)).where(Message.created_at >= since))
    open_convs = await db.execute(select(func.count(Conversation.id)).where(Conversation.status == "open"))

    return {
        "days": days,
        "message_volume": [
            {"date": d, **v} for d, v in sorted(day_map.items())
        ],
        "contact_growth": [
            {"date": d, "count": contact_map.get(d, 0)}
            for d in sorted(day_map.keys())
        ],
        "broadcast_summary": broadcast_summary,
        "template_performance": template_perf,
        "totals": {
            "contacts": total_contacts.scalar(),
            "messages_period": total_messages.scalar(),
            "open_conversations": open_convs.scalar(),
        },
    }
