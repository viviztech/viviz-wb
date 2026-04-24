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
    # Exclude Meta sample templates (hello_world) — only work with test numbers, not real recipients
    tpls = (await db.execute(
        select(MessageTemplate).where(
            MessageTemplate.status == "APPROVED",
            MessageTemplate.name != "hello_world",
        )
    )).scalars().all()

    return templates.TemplateResponse("dashboard/broadcasts.html", {
        "request": request,
        "admin_name": request.session.get("admin_name", "Admin"),
        "broadcasts": broadcasts,
        "templates": tpls,
        "page": "broadcasts",
        "now": datetime.utcnow().strftime("%Y-%m-%dT%H:%M"),
    })


@router.post("/create")
async def create_broadcast(
    request: Request,
    name: str = Form(...),
    template_name: str = Form(...),
    target_tags: str = Form(""),
    scheduled_at: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    tag_list = [t.strip() for t in target_tags.split(",") if t.strip()]

    query = select(Contact).where(Contact.is_opted_in == True, Contact.is_blocked == False)
    contacts = (await db.execute(query)).scalars().all()
    if tag_list:
        contacts = [c for c in contacts if any(t in (c.tags or []) for t in tag_list)]

    scheduled_dt = None
    status = "draft"
    if scheduled_at:
        try:
            scheduled_dt = datetime.fromisoformat(scheduled_at)
            status = "scheduled"
        except ValueError:
            return JSONResponse({"error": "Invalid scheduled time format"}, status_code=400)

    broadcast = Broadcast(
        name=name,
        template_name=template_name,
        target_tags=tag_list,
        total_count=len(contacts),
        status=status,
        scheduled_at=scheduled_dt,
        created_by=request.session.get("admin_email"),
    )
    db.add(broadcast)
    await db.flush()

    for contact in contacts:
        db.add(BroadcastRecipient(broadcast_id=broadcast.id, contact_id=contact.id))

    await db.commit()
    return JSONResponse({
        "status": "created",
        "id": broadcast.id,
        "total": len(contacts),
        "scheduled": scheduled_dt.isoformat() if scheduled_dt else None,
    })


@router.get("/status")
async def broadcasts_status(request: Request, db: AsyncSession = Depends(get_db)):
    """Return live status for all running/scheduled broadcasts — used for polling."""
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    rows = (await db.execute(
        select(Broadcast).where(Broadcast.status.in_(["running", "scheduled"]))
    )).scalars().all()
    return JSONResponse([
        {
            "id": b.id,
            "status": b.status,
            "sent_count": b.sent_count or 0,
            "failed_count": b.failed_count or 0,
            "delivered_count": b.delivered_count or 0,
            "total_count": b.total_count or 0,
        }
        for b in rows
    ])


@router.post("/{broadcast_id}/send")
async def send_broadcast(broadcast_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    broadcast = (await db.execute(select(Broadcast).where(Broadcast.id == broadcast_id))).scalar_one_or_none()
    if not broadcast:
        raise HTTPException(404, "Not found")
    if broadcast.status not in ("draft", "scheduled"):
        return JSONResponse({"error": "Already sent or running"}, status_code=400)

    broadcast.status = "running"
    broadcast.started_at = datetime.utcnow()
    await db.commit()

    asyncio.create_task(_send_broadcast_messages(broadcast_id))
    return JSONResponse({"status": "started"})


@router.get("/{broadcast_id}/failures")
async def broadcast_failures(broadcast_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Return failed recipients with error messages."""
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    failures = (await db.execute(
        select(BroadcastRecipient, Contact)
        .join(Contact, BroadcastRecipient.contact_id == Contact.id)
        .where(BroadcastRecipient.broadcast_id == broadcast_id, BroadcastRecipient.status == "failed")
    )).all()
    return JSONResponse([
        {"phone": c.phone, "name": c.name or c.profile_name or "", "error": r.error_message or "Unknown error"}
        for r, c in failures
    ])


@router.post("/{broadcast_id}/cancel")
async def cancel_broadcast(broadcast_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    broadcast = (await db.execute(select(Broadcast).where(Broadcast.id == broadcast_id))).scalar_one_or_none()
    if not broadcast:
        raise HTTPException(404, "Not found")
    if broadcast.status not in ("draft", "scheduled"):
        return JSONResponse({"error": "Can only cancel draft or scheduled broadcasts"}, status_code=400)

    broadcast.status = "cancelled"
    await db.commit()
    return JSONResponse({"status": "cancelled"})


async def _send_broadcast_messages(broadcast_id: int):
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        broadcast = (await db.execute(select(Broadcast).where(Broadcast.id == broadcast_id))).scalar_one_or_none()
        recipients = (await db.execute(
            select(BroadcastRecipient).where(
                BroadcastRecipient.broadcast_id == broadcast_id,
                BroadcastRecipient.status == "pending",
            )
        )).scalars().all()

        sent = 0
        failed = 0
        for recipient in recipients:
            contact = (await db.execute(select(Contact).where(Contact.id == recipient.contact_id))).scalar_one_or_none()
            if not contact:
                recipient.status = "failed"
                recipient.error_message = "Contact not found"
                failed += 1
                await db.commit()
                continue
            try:
                result = await whatsapp.send_template(contact.phone, broadcast.template_name)
                wa_msg_id = result.get("messages", [{}])[0].get("id")
                recipient.wa_message_id = wa_msg_id
                recipient.status = "sent"
                recipient.sent_at = datetime.utcnow()
                sent += 1
            except Exception as ex:
                # Extract readable Meta error message from HTTP response body
                error_msg = str(ex)
                try:
                    import httpx
                    if isinstance(ex, httpx.HTTPStatusError):
                        body = ex.response.json()
                        meta_err = body.get("error", {})
                        error_msg = meta_err.get("error_user_msg") or meta_err.get("message") or error_msg
                except Exception:
                    pass
                recipient.status = "failed"
                recipient.error_message = error_msg[:500]
                failed += 1
                logger.error(f"Broadcast send error for {contact.phone}: {error_msg}")

            await db.commit()
            await asyncio.sleep(0.05)  # ~20 msg/sec, well within Meta's 80/sec limit

        broadcast.sent_count = sent
        broadcast.failed_count = failed
        broadcast.status = "completed"
        broadcast.completed_at = datetime.utcnow()
        await db.commit()
        logger.info(f"Broadcast {broadcast_id} completed: {sent} sent, {failed} failed")
