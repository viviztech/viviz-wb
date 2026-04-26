from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from datetime import datetime
from typing import Optional
import asyncio
import logging
import json

from app.database import get_db
from app.models.broadcast import Broadcast, BroadcastRecipient
from app.models.contact import Contact
from app.models.template import MessageTemplate
from app.services.whatsapp import whatsapp

router = APIRouter(prefix="/broadcasts", tags=["broadcasts"])
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)

MAX_RETRY_ATTEMPTS = 3
SEND_RATE_PER_SEC = 15  # stay well under Meta's 80/sec limit


def _auth(request: Request):
    return request.session.get("admin_email")


def _build_components(resolved_vars: dict) -> Optional[list]:
    """Build Meta template components from resolved variable dict {1: val, 2: val}."""
    if not resolved_vars:
        return None
    params = [{"type": "text", "text": str(v)} for k, v in sorted(resolved_vars.items(), key=lambda x: str(x[0]))]
    return [{"type": "body", "parameters": params}]


def _resolve_variables(variable_mapping: dict, contact: Contact, static_vars: dict) -> dict:
    """
    Resolve per-recipient variables.
    variable_mapping: {"1": "name"} means {{1}} = contact.name
    static_vars: {"2": "50% OFF"} means {{2}} = literal value
    """
    resolved = dict(static_vars or {})
    field_map = {
        "name": contact.name or contact.profile_name or "",
        "phone": contact.phone or "",
        "email": contact.email or "",
        "first_name": (contact.name or contact.profile_name or "").split()[0] if (contact.name or contact.profile_name) else "",
    }
    for var_idx, field_name in (variable_mapping or {}).items():
        resolved[var_idx] = field_map.get(field_name, "")
    return resolved


def _filter_contacts_by_segment(contacts: list, segment: dict) -> list:
    """Filter contacts by segment criteria dict."""
    if not segment:
        return contacts
    result = []
    for c in contacts:
        match = True
        if segment.get("has_name") and not (c.name or c.profile_name):
            match = False
        if segment.get("has_email") and not c.email:
            match = False
        tags_include = segment.get("tags_include", [])
        if tags_include and not any(t in (c.tags or []) for t in tags_include):
            match = False
        tags_exclude = segment.get("tags_exclude", [])
        if tags_exclude and any(t in (c.tags or []) for t in tags_exclude):
            match = False
        if match:
            result.append(c)
    return result


@router.get("", response_class=HTMLResponse)
async def broadcasts_list(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return RedirectResponse("/login", status_code=302)

    all_broadcasts = (await db.execute(
        select(Broadcast).order_by(desc(Broadcast.created_at)).limit(100)
    )).scalars().all()

    tpls = (await db.execute(
        select(MessageTemplate).where(
            MessageTemplate.status == "APPROVED",
            MessageTemplate.name != "hello_world",
        )
    )).scalars().all()

    total_sent = sum(b.sent_count or 0 for b in all_broadcasts)
    total_delivered = sum(b.delivered_count or 0 for b in all_broadcasts)
    total_read = sum(b.read_count or 0 for b in all_broadcasts)
    total_failed = sum(b.failed_count or 0 for b in all_broadcasts)

    all_contacts_q = await db.execute(select(Contact.tags).where(Contact.tags.isnot(None)))
    all_tags: set = set()
    for (tags,) in all_contacts_q:
        if tags:
            all_tags.update(tags)

    return templates.TemplateResponse("dashboard/broadcasts.html", {
        "request": request,
        "admin_name": request.session.get("admin_name", "Admin"),
        "broadcasts": all_broadcasts,
        "templates": tpls,
        "all_tags": sorted(all_tags),
        "page": "broadcasts",
        "now": datetime.utcnow().strftime("%Y-%m-%dT%H:%M"),
        "stats": {
            "total": len(all_broadcasts),
            "sent": total_sent,
            "delivered": total_delivered,
            "read": total_read,
            "failed": total_failed,
        },
    })


@router.post("/preview-count")
async def preview_count(request: Request, db: AsyncSession = Depends(get_db)):
    """Return estimated recipient count for given targeting parameters."""
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    data = await request.json()
    target_mode = data.get("target_mode", "all")
    target_tags = data.get("target_tags", [])
    segment_filter = data.get("segment_filter", {})

    contacts = (await db.execute(
        select(Contact).where(Contact.is_opted_in == True, Contact.is_blocked == False)
    )).scalars().all()

    if target_mode == "tags" and target_tags:
        contacts = [c for c in contacts if any(t in (c.tags or []) for t in target_tags)]
    elif target_mode == "segment":
        contacts = _filter_contacts_by_segment(contacts, segment_filter)

    return JSONResponse({"count": len(contacts)})


@router.post("/create")
async def create_broadcast(
    request: Request,
    name: str = Form(...),
    template_name: str = Form(...),
    template_language: str = Form("en"),
    target_mode: str = Form("all"),
    target_tags: str = Form(""),
    segment_filter: str = Form("{}"),
    variable_mapping: str = Form("{}"),
    static_variables: str = Form("{}"),
    scheduled_at: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    tag_list = [t.strip() for t in target_tags.split(",") if t.strip()]

    try:
        var_mapping = json.loads(variable_mapping) if variable_mapping else {}
        static_vars = json.loads(static_variables) if static_variables else {}
        seg_filter = json.loads(segment_filter) if segment_filter else {}
    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid JSON in variables or segment"}, status_code=400)

    contacts = (await db.execute(
        select(Contact).where(Contact.is_opted_in == True, Contact.is_blocked == False)
    )).scalars().all()

    if target_mode == "tags" and tag_list:
        contacts = [c for c in contacts if any(t in (c.tags or []) for t in tag_list)]
    elif target_mode == "segment":
        contacts = _filter_contacts_by_segment(contacts, seg_filter)

    if not contacts:
        return JSONResponse({"error": "No eligible opted-in contacts found for this targeting"}, status_code=400)

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
        template_language=template_language,
        variable_mapping=var_mapping,
        variables=static_vars,
        target_tags=tag_list,
        target_mode=target_mode,
        segment_filter=seg_filter,
        total_count=len(contacts),
        status=status,
        scheduled_at=scheduled_dt,
        created_by=request.session.get("admin_email"),
    )
    db.add(broadcast)
    await db.flush()

    for contact in contacts:
        resolved = _resolve_variables(var_mapping, contact, static_vars)
        db.add(BroadcastRecipient(
            broadcast_id=broadcast.id,
            contact_id=contact.id,
            resolved_variables=resolved,
        ))

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
            "read_count": b.read_count or 0,
            "total_count": b.total_count or 0,
        }
        for b in rows
    ])


@router.get("/{broadcast_id}/detail")
async def broadcast_detail(broadcast_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Full broadcast analytics for detail modal."""
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    b = (await db.execute(select(Broadcast).where(Broadcast.id == broadcast_id))).scalar_one_or_none()
    if not b:
        raise HTTPException(404, "Not found")

    sent = b.sent_count or 0
    delivered = b.delivered_count or 0
    read = b.read_count or 0
    failed = b.failed_count or 0

    return JSONResponse({
        "id": b.id,
        "name": b.name,
        "template_name": b.template_name,
        "status": b.status,
        "total_count": b.total_count or 0,
        "sent_count": sent,
        "delivered_count": delivered,
        "read_count": read,
        "failed_count": failed,
        "retry_count": b.retry_count or 0,
        "delivery_rate": round(delivered / sent * 100, 1) if sent > 0 else 0,
        "read_rate": round(read / delivered * 100, 1) if delivered > 0 else 0,
        "scheduled_at": b.scheduled_at.isoformat() if b.scheduled_at else None,
        "started_at": b.started_at.isoformat() if b.started_at else None,
        "completed_at": b.completed_at.isoformat() if b.completed_at else None,
        "created_at": b.created_at.isoformat(),
        "target_mode": b.target_mode or "all",
        "target_tags": b.target_tags or [],
        "variable_mapping": b.variable_mapping or {},
    })


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
        {
            "phone": c.phone,
            "name": c.name or c.profile_name or "",
            "error": r.error_message or "Unknown error",
            "retries": r.retry_attempts or 0,
        }
        for r, c in failures
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


@router.post("/{broadcast_id}/retry-failed")
async def retry_failed(broadcast_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Re-queue all failed recipients for retry."""
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    broadcast = (await db.execute(select(Broadcast).where(Broadcast.id == broadcast_id))).scalar_one_or_none()
    if not broadcast:
        raise HTTPException(404, "Not found")
    if broadcast.status == "running":
        return JSONResponse({"error": "Broadcast is already running"}, status_code=400)

    failed_recipients = (await db.execute(
        select(BroadcastRecipient).where(
            BroadcastRecipient.broadcast_id == broadcast_id,
            BroadcastRecipient.status == "failed",
            BroadcastRecipient.retry_attempts < MAX_RETRY_ATTEMPTS,
        )
    )).scalars().all()

    if not failed_recipients:
        return JSONResponse({"error": "No retryable failures found"}, status_code=400)

    for r in failed_recipients:
        r.status = "pending"

    broadcast.status = "running"
    broadcast.started_at = datetime.utcnow()
    broadcast.retry_count = (broadcast.retry_count or 0) + 1
    await db.commit()

    asyncio.create_task(_send_broadcast_messages(broadcast_id))
    return JSONResponse({"status": "retrying", "count": len(failed_recipients)})


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


@router.delete("/{broadcast_id}")
async def delete_broadcast(broadcast_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    broadcast = (await db.execute(select(Broadcast).where(Broadcast.id == broadcast_id))).scalar_one_or_none()
    if not broadcast:
        raise HTTPException(404, "Not found")
    if broadcast.status == "running":
        return JSONResponse({"error": "Cannot delete a running broadcast"}, status_code=400)

    from sqlalchemy import delete as sql_delete
    await db.execute(sql_delete(BroadcastRecipient).where(BroadcastRecipient.broadcast_id == broadcast_id))
    await db.delete(broadcast)
    await db.commit()
    return JSONResponse({"status": "deleted"})


async def _is_mm_lite_active(db) -> bool:
    """Return True if MM Lite onboarding is complete for this WABA."""
    from app.models.mm_lite import MMLiteOnboarding
    from app.config import settings as _settings
    waba_id = _settings.whatsapp_business_account_id
    if not waba_id:
        return False
    record = (await db.execute(
        select(MMLiteOnboarding).where(MMLiteOnboarding.waba_id == waba_id)
    )).scalar_one_or_none()
    return record is not None and record.status == "active"


async def _get_template_category(template_name: str, db) -> str:
    """Look up the category of a template from the local DB. Defaults to UTILITY."""
    tpl = (await db.execute(
        select(MessageTemplate).where(MessageTemplate.name == template_name)
    )).scalar_one_or_none()
    return (tpl.category or "UTILITY").upper() if tpl else "UTILITY"


async def _send_broadcast_messages(broadcast_id: int):
    """
    Core send engine with rate limiting and retry support.
    Rate: SEND_RATE_PER_SEC msgs/sec (far below Meta's 80/sec cap).
    Auto-retries transient failures up to MAX_RETRY_ATTEMPTS with exponential backoff.
    Uses MM Lite delivery when WABA is onboarded and template is MARKETING category.
    """
    from app.database import AsyncSessionLocal
    from app.services.mm_lite import send_mm_lite_template

    async with AsyncSessionLocal() as db:
        broadcast = (await db.execute(select(Broadcast).where(Broadcast.id == broadcast_id))).scalar_one_or_none()
        if not broadcast:
            return

        recipients = (await db.execute(
            select(BroadcastRecipient).where(
                BroadcastRecipient.broadcast_id == broadcast_id,
                BroadcastRecipient.status == "pending",
            )
        )).scalars().all()

        sent = broadcast.sent_count or 0
        failed = broadcast.failed_count or 0
        delay = 1.0 / SEND_RATE_PER_SEC

        # Determine whether to route through MM Lite for this broadcast
        use_mm_lite = (
            await _is_mm_lite_active(db)
            and await _get_template_category(broadcast.template_name, db) == "MARKETING"
        )
        if use_mm_lite:
            logger.info(f"Broadcast {broadcast_id}: routing through MM Lite")

        for recipient in recipients:
            contact = (await db.execute(select(Contact).where(Contact.id == recipient.contact_id))).scalar_one_or_none()
            if not contact:
                recipient.status = "failed"
                recipient.error_message = "Contact not found"
                failed += 1
                await db.commit()
                continue

            components = _build_components(recipient.resolved_variables or {})
            success = False
            last_error = ""

            # Try with components first; if Meta returns #132000 (param mismatch),
            # fall back to sending without components (template has no variables on Meta side).
            send_attempts = [(components,)] if components else [(None,)]
            if components:
                send_attempts.append((None,))  # fallback

            for components_try in send_attempts:
                comps = components_try[0]
                for attempt in range(MAX_RETRY_ATTEMPTS):
                    try:
                        if use_mm_lite:
                            result = await send_mm_lite_template(
                                contact.phone,
                                broadcast.template_name,
                                language_code=broadcast.template_language or "en",
                                components=comps,
                            )
                        else:
                            result = await whatsapp.send_template(
                                contact.phone,
                                broadcast.template_name,
                                language_code=broadcast.template_language or "en",
                                components=comps,
                            )
                        wa_msg_id = result.get("messages", [{}])[0].get("id")
                        recipient.wa_message_id = wa_msg_id
                        recipient.status = "sent"
                        recipient.sent_at = datetime.utcnow()
                        recipient.retry_attempts = attempt
                        sent += 1
                        success = True
                        break
                    except Exception as ex:
                        last_error = _extract_meta_error(ex)
                        recipient.retry_attempts = attempt + 1
                        if _is_param_mismatch_error(last_error):
                            break  # break inner loop → try fallback (no components)
                        if _is_fatal_error(last_error):
                            break
                        if attempt < MAX_RETRY_ATTEMPTS - 1:
                            await asyncio.sleep(2 ** attempt)
                if success:
                    break

            if not success:
                recipient.status = "failed"
                recipient.error_message = last_error[:500]
                failed += 1
                logger.error(f"Broadcast {broadcast_id}: failed for {contact.phone}: {last_error}")

            broadcast.sent_count = sent
            broadcast.failed_count = failed
            await db.commit()
            await asyncio.sleep(delay)

        broadcast.status = "completed"
        broadcast.completed_at = datetime.utcnow()
        await db.commit()
        logger.info(f"Broadcast {broadcast_id} completed: {sent} sent, {failed} failed")


def _extract_meta_error(ex: Exception) -> str:
    try:
        import httpx
        if isinstance(ex, httpx.HTTPStatusError):
            body = ex.response.json()
            meta_err = body.get("error", {})
            return meta_err.get("error_user_msg") or meta_err.get("message") or str(ex)
    except Exception:
        pass
    return str(ex)


def _is_param_mismatch_error(error_msg: str) -> bool:
    """Meta #132000 — template approved without variables, but we sent parameters."""
    return "132000" in error_msg or "number of parameters does not match" in error_msg.lower()


def _is_fatal_error(error_msg: str) -> bool:
    """Errors that should not be retried (invalid number, opted-out, etc.)."""
    fatal_fragments = [
        "not a valid whatsapp",
        "recipient phone number not in allowed list",
        "phone number is not valid",
        "the number you are trying to message",
        "unknown contact",
    ]
    lower = error_msg.lower()
    return any(f in lower for f in fatal_fragments)
