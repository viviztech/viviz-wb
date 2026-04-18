from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from datetime import datetime
from app.database import get_db
from app.models.broadcast import Broadcast, BroadcastRecipient
from app.models.contact import Contact
from app.models.template import MessageTemplate
from app.services.whatsapp import whatsapp
import asyncio
import logging

router = APIRouter(prefix="/broadcasts", tags=["broadcasts"])
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)


def _auth(request: Request):
    return request.session.get("admin_email")


@router.get("", response_class=HTMLResponse)
async def broadcasts_list(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return RedirectResponse("/login", status_code=302)

    broadcasts = (await db.execute(select(Broadcast).order_by(desc(Broadcast.created_at)))).scalars().all()
    tpls = (await db.execute(select(MessageTemplate).where(MessageTemplate.status == "APPROVED"))).scalars().all()

    return templates.TemplateResponse("dashboard/broadcasts.html", {
        "request": request,
        "admin_name": request.session.get("admin_name", "Admin"),
        "broadcasts": broadcasts,
        "templates": tpls,
        "page": "broadcasts",
    })


@router.post("/create")
async def create_broadcast(
    request: Request,
    name: str = Form(...),
    template_name: str = Form(...),
    target_tags: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    tag_list = [t.strip() for t in target_tags.split(",") if t.strip()]

    query = select(Contact).where(Contact.is_opted_in == True, Contact.is_blocked == False)
    contacts = (await db.execute(query)).scalars().all()
    if tag_list:
        contacts = [c for c in contacts if any(t in (c.tags or []) for t in tag_list)]

    broadcast = Broadcast(
        name=name,
        template_name=template_name,
        target_tags=tag_list,
        total_count=len(contacts),
        status="draft",
        created_by=request.session.get("admin_email"),
    )
    db.add(broadcast)
    await db.flush()

    for contact in contacts:
        db.add(BroadcastRecipient(broadcast_id=broadcast.id, contact_id=contact.id))

    await db.flush()
    return JSONResponse({"status": "created", "id": broadcast.id, "total": len(contacts)})


@router.post("/{broadcast_id}/send")
async def send_broadcast(broadcast_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    broadcast = (await db.execute(select(Broadcast).where(Broadcast.id == broadcast_id))).scalar_one_or_none()
    if not broadcast:
        raise HTTPException(404, "Not found")
    if broadcast.status not in ("draft",):
        return JSONResponse({"error": "Already sent or running"}, status_code=400)

    broadcast.status = "running"
    broadcast.started_at = datetime.utcnow()
    await db.commit()

    # Run sending in background
    asyncio.create_task(_send_broadcast_messages(broadcast_id))
    return JSONResponse({"status": "started"})


async def _send_broadcast_messages(broadcast_id: int):
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        broadcast = (await db.execute(select(Broadcast).where(Broadcast.id == broadcast_id))).scalar_one_or_none()
        recipients = (await db.execute(
            select(BroadcastRecipient).where(BroadcastRecipient.broadcast_id == broadcast_id, BroadcastRecipient.status == "pending")
        )).scalars().all()

        sent = 0
        failed = 0
        for recipient in recipients:
            contact = (await db.execute(select(Contact).where(Contact.id == recipient.contact_id))).scalar_one_or_none()
            try:
                result = await whatsapp.send_template(contact.phone, broadcast.template_name)
                wa_msg_id = result.get("messages", [{}])[0].get("id")
                recipient.wa_message_id = wa_msg_id
                recipient.status = "sent"
                recipient.sent_at = datetime.utcnow()
                sent += 1
            except Exception as ex:
                recipient.status = "failed"
                recipient.error_message = str(ex)
                failed += 1
                logger.error(f"Broadcast send error for {contact.phone}: {ex}")

            await db.commit()
            await asyncio.sleep(0.1)  # Rate limiting: ~10 msg/sec

        broadcast.sent_count = sent
        broadcast.failed_count = failed
        broadcast.status = "completed"
        broadcast.completed_at = datetime.utcnow()
        await db.commit()
