from fastapi import APIRouter, Request, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, or_, delete
from app.database import get_db
from app.models.contact import Contact
from app.services.audit import log_event
from app.services.consent import has_active_consent, record_consent
from datetime import datetime
import csv, io, json

router = APIRouter(prefix="/contacts", tags=["contacts"])
templates = Jinja2Templates(directory="app/templates")


def _auth(request: Request):
    return request.session.get("admin_email")


@router.get("", response_class=HTMLResponse)
async def contacts_list(
    request: Request,
    q: str = "",
    page: int = 1,
    db: AsyncSession = Depends(get_db),
):
    if not _auth(request):
        return RedirectResponse("/login", status_code=302)

    page = max(1, page)
    per_page = 50
    offset = (page - 1) * per_page

    base = select(Contact).order_by(desc(Contact.created_at))
    count_q = select(func.count(Contact.id))
    if q:
        filt = or_(Contact.phone.contains(q), Contact.name.ilike(f"%{q}%"), Contact.profile_name.ilike(f"%{q}%"))
        base = base.where(filt)
        count_q = count_q.where(filt)

    total = (await db.execute(count_q)).scalar()
    total_pages = max(1, (total + per_page - 1) // per_page)
    contacts = (await db.execute(base.offset(offset).limit(per_page))).scalars().all()

    return templates.TemplateResponse("dashboard/contacts.html", {
        "request": request,
        "admin_name": request.session.get("admin_name", "Admin"),
        "contacts": contacts,
        "q": q,
        "page": "contacts",
        "current_page": page,
        "total_pages": total_pages,
        "total": total,
    })


@router.post("/add")
async def add_contact(
    request: Request,
    phone: str = Form(...),
    name: str = Form(""),
    email: str = Form(""),
    tags: str = Form(""),
    notes: str = Form(""),
    marketing_consent_confirmed: str = Form("false"),
    consent_evidence: str = Form(""),
    consent_proof_reference: str = Form(""),
    consent_disclosure_text: str = Form(""),
    consent_obtained_at: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    phone = phone.strip().replace(" ", "").replace("+", "")
    if not phone.startswith("91"):
        phone = "91" + phone

    existing = (await db.execute(select(Contact).where(Contact.phone == phone))).scalar_one_or_none()
    if existing:
        return JSONResponse({"error": "Contact already exists"}, status_code=400)

    consent_requested = marketing_consent_confirmed.lower() == "true"
    if consent_requested and not all((consent_evidence.strip(), consent_disclosure_text.strip(), consent_obtained_at.strip())):
        return JSONResponse(
            {"error": "Consent evidence, exact disclosure wording, and consent date are required"},
            status_code=400,
        )
    consent_at = None
    if consent_requested:
        try:
            consent_at = datetime.fromisoformat(consent_obtained_at)
        except ValueError:
            return JSONResponse({"error": "Invalid consent date"}, status_code=400)

    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    contact = Contact(
        phone=phone, name=name, email=email, tags=tag_list, notes=notes,
        is_opted_in=False,
    )
    db.add(contact)
    await db.flush()
    if consent_requested:
        await record_consent(
            db, contact, "marketing", "granted", "manual_admin",
            consent_evidence, request.session.get("admin_email", "admin"),
            disclosure_text=consent_disclosure_text,
            proof_reference=consent_proof_reference,
            occurred_at=consent_at,
        )
    return JSONResponse({"status": "created", "id": contact.id})


@router.post("/{contact_id}/update")
async def update_contact(
    contact_id: int,
    request: Request,
    name: str = Form(""),
    email: str = Form(""),
    tags: str = Form(""),
    notes: str = Form(""),
    is_opted_in: str = Form("true"),
    consent_evidence: str = Form(""),
    consent_proof_reference: str = Form(""),
    consent_disclosure_text: str = Form(""),
    consent_obtained_at: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    contact = (await db.execute(select(Contact).where(Contact.id == contact_id))).scalar_one_or_none()
    if not contact:
        raise HTTPException(404, "Not found")
    new_opted_in = is_opted_in.lower() == "true"
    currently_opted_in = await has_active_consent(db, contact.id, "marketing")
    if new_opted_in != currently_opted_in:
        if new_opted_in and not all((consent_evidence.strip(), consent_disclosure_text.strip(), consent_obtained_at.strip())):
            return JSONResponse(
                {"error": "Consent evidence, exact disclosure wording, and consent date are required"},
                status_code=400,
            )
        consent_at = None
        if new_opted_in:
            try:
                consent_at = datetime.fromisoformat(consent_obtained_at)
            except ValueError:
                return JSONResponse({"error": "Invalid consent date"}, status_code=400)
        await record_consent(
            db, contact, "marketing", "granted" if new_opted_in else "revoked",
            "manual_admin", consent_evidence or "Revoked by administrator",
            request.session.get("admin_email", "admin"),
            disclosure_text=consent_disclosure_text,
            proof_reference=consent_proof_reference,
            occurred_at=consent_at,
        )

    contact.name = name
    contact.email = email
    contact.tags = [t.strip() for t in tags.split(",") if t.strip()]
    contact.notes = notes
    contact.is_opted_in = new_opted_in
    await db.commit()
    return JSONResponse({"status": "updated"})


@router.post("/{contact_id}/block")
async def toggle_block(contact_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    contact = (await db.execute(select(Contact).where(Contact.id == contact_id))).scalar_one_or_none()
    if not contact:
        raise HTTPException(404, "Not found")
    contact.is_blocked = not contact.is_blocked
    return JSONResponse({"status": "blocked" if contact.is_blocked else "unblocked"})


@router.post("/import")
async def import_contacts(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    if not file.filename.endswith(".csv"):
        return JSONResponse({"error": "Only CSV files are supported"}, status_code=400)

    content = await file.read()
    try:
        text = content.decode("utf-8-sig")  # handle BOM
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    # Normalise header names to lowercase stripped
    reader.fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]

    added = 0
    skipped = 0
    errors = []

    for i, row in enumerate(reader, start=2):
        phone = (row.get("phone") or row.get("mobile") or row.get("number") or "").strip().replace(" ", "").replace("+", "")
        if not phone:
            errors.append(f"Row {i}: missing phone")
            continue
        if not phone.startswith("91"):
            phone = "91" + phone

        existing = (await db.execute(select(Contact).where(Contact.phone == phone))).scalar_one_or_none()
        if existing:
            skipped += 1
            continue

        name = (row.get("name") or row.get("full name") or "").strip()
        email = (row.get("email") or "").strip()
        tags_raw = (row.get("tags") or row.get("tag") or "").strip()
        tag_list = [t.strip() for t in tags_raw.split(";") if t.strip()] or \
                   [t.strip() for t in tags_raw.split(",") if t.strip()]
        notes = (row.get("notes") or row.get("note") or "").strip()

        consent_value = (row.get("marketing_opt_in") or row.get("marketing consent") or "").strip().lower()
        consent_evidence = (row.get("consent_evidence") or row.get("consent evidence") or "").strip()
        proof_reference = (row.get("consent_proof_reference") or row.get("proof reference") or "").strip()
        consent_disclosure = (row.get("consent_disclosure") or row.get("consent disclosure") or "").strip()
        consent_at_raw = (row.get("consent_at") or row.get("consent date") or "").strip()
        wants_marketing = consent_value in {"yes", "true", "1", "granted"}
        consent_at = None
        if wants_marketing and not all((consent_evidence, consent_disclosure, consent_at_raw)):
            errors.append(f"Row {i}: marketing consent needs consent_evidence, consent_disclosure, and consent_at; imported as not opted in")
            wants_marketing = False
        if wants_marketing:
            try:
                consent_at = datetime.fromisoformat(consent_at_raw)
            except ValueError:
                errors.append(f"Row {i}: invalid consent_at; imported as not opted in")
                wants_marketing = False

        contact = Contact(
            phone=phone, name=name, email=email, tags=tag_list, notes=notes,
            is_opted_in=False,
        )
        db.add(contact)
        await db.flush()
        if wants_marketing:
            await record_consent(
                db, contact, "marketing", "granted", "csv_import",
                consent_evidence, request.session.get("admin_email", "admin"),
                disclosure_text=consent_disclosure,
                proof_reference=proof_reference,
                occurred_at=consent_at,
            )
        added += 1

    await db.commit()
    return JSONResponse({"added": added, "skipped": skipped, "errors": errors[:10]})


@router.get("/tags")
async def list_tags(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    contacts = (await db.execute(select(Contact.tags))).scalars().all()
    tag_set = set()
    for tags in contacts:
        for t in (tags or []):
            if t:
                tag_set.add(t)
    return JSONResponse(sorted(tag_set))


def _match_tags(contacts, tags):
    tag_set = set(tags)
    return [c for c in contacts if tag_set.intersection(c.tags or [])]


@router.post("/bulk-delete-preview")
async def bulk_delete_preview(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    body = await request.json()
    tags = body.get("tags", [])
    if not tags or not isinstance(tags, list):
        return JSONResponse({"count": 0})
    all_contacts = (await db.execute(select(Contact))).scalars().all()
    return JSONResponse({"count": len(_match_tags(all_contacts, tags))})


@router.post("/bulk-delete")
async def bulk_delete_by_tags(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    body = await request.json()
    tags = body.get("tags", [])
    if not tags or not isinstance(tags, list):
        return JSONResponse({"error": "Provide a non-empty list of tags"}, status_code=400)

    all_contacts = (await db.execute(select(Contact))).scalars().all()
    to_delete = _match_tags(all_contacts, tags)
    if not to_delete:
        return JSONResponse({"deleted": 0})

    ids = [c.id for c in to_delete]
    from app.models.broadcast import BroadcastRecipient
    from app.models.campaign_flow import CampaignFlowState
    from app.models.consent import ConsentEvent
    from app.models.conversation import Conversation, Message
    from app.models.drip_campaign import DripEnrollment

    # SQLAlchemy IN clauses work on both SQLite and PostgreSQL.
    conv_ids = (await db.execute(
        select(Conversation.id).where(Conversation.contact_id.in_(ids))
    )).scalars().all()
    if conv_ids:
        await db.execute(delete(Message).where(Message.conversation_id.in_(conv_ids)))
    await db.execute(delete(BroadcastRecipient).where(BroadcastRecipient.contact_id.in_(ids)))
    await db.execute(delete(Conversation).where(Conversation.contact_id.in_(ids)))
    await db.execute(delete(DripEnrollment).where(DripEnrollment.contact_id.in_(ids)))
    await db.execute(delete(CampaignFlowState).where(CampaignFlowState.contact_id.in_(ids)))
    await db.execute(delete(ConsentEvent).where(ConsentEvent.contact_id.in_(ids)))
    await db.execute(delete(Contact).where(Contact.id.in_(ids)))
    await db.commit()
    return JSONResponse({"deleted": len(ids)})


@router.get("/{contact_id}/export-data")
async def export_contact_data(contact_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Fulfil a data subject access/portability request — full export of everything stored for this contact."""
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    contact = (await db.execute(select(Contact).where(Contact.id == contact_id))).scalar_one_or_none()
    if not contact:
        raise HTTPException(404, "Not found")

    from app.models.conversation import Conversation, Message
    from app.models.broadcast import BroadcastRecipient
    from app.models.consent import ConsentEvent

    conversations = (await db.execute(
        select(Conversation).where(Conversation.contact_id == contact_id)
    )).scalars().all()
    conv_ids = [c.id for c in conversations]
    messages = []
    if conv_ids:
        messages = (await db.execute(
            select(Message).where(Message.conversation_id.in_(conv_ids)).order_by(Message.created_at)
        )).scalars().all()
    recipients = (await db.execute(
        select(BroadcastRecipient).where(BroadcastRecipient.contact_id == contact_id)
    )).scalars().all()
    consent_events = (await db.execute(
        select(ConsentEvent).where(ConsentEvent.contact_id == contact_id).order_by(ConsentEvent.created_at)
    )).scalars().all()

    data = {
        "contact": {
            "id": contact.id, "phone": contact.phone, "name": contact.name,
            "profile_name": contact.profile_name, "email": contact.email,
            "tags": contact.tags, "notes": contact.notes,
            "is_opted_in": contact.is_opted_in, "opt_in_source": contact.opt_in_source,
            "opt_in_at": contact.opt_in_at.isoformat() if contact.opt_in_at else None,
            "opt_out_at": contact.opt_out_at.isoformat() if contact.opt_out_at else None,
            "is_blocked": contact.is_blocked,
            "created_at": contact.created_at.isoformat(),
        },
        "conversations": [
            {"id": c.id, "status": c.status, "created_at": c.created_at.isoformat()}
            for c in conversations
        ],
        "messages": [
            {
                "id": m.id, "direction": m.direction.value, "type": m.message_type.value,
                "content": m.content, "status": m.status.value, "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ],
        "broadcast_recipients": [
            {
                "broadcast_id": r.broadcast_id, "status": r.status,
                "sent_at": r.sent_at.isoformat() if r.sent_at else None,
            }
            for r in recipients
        ],
        "consent_events": [
            {
                "category": e.category, "action": e.action,
                "business_name": e.business_name, "disclosure_text": e.disclosure_text,
                "source": e.source, "evidence": e.evidence,
                "proof_reference": e.proof_reference,
                "privacy_policy_url": e.privacy_policy_url,
                "occurred_at": e.occurred_at.isoformat(),
                "created_at": e.created_at.isoformat(),
            }
            for e in consent_events
        ],
    }

    await log_event(db, actor=request.session.get("admin_email", "admin"), action="contact_data_export",
                     target_type="contact", target_id=contact.id, meta={"phone": contact.phone})
    await db.commit()

    return JSONResponse(data, headers={
        "Content-Disposition": f"attachment; filename=contact_{contact_id}_data_export.json"
    })


@router.get("/{contact_id}/consent-history")
async def contact_consent_history(contact_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Return the append-only consent evidence trail for an authenticated compliance review."""
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    contact = (await db.execute(select(Contact).where(Contact.id == contact_id))).scalar_one_or_none()
    if not contact:
        raise HTTPException(404, "Not found")
    from app.models.consent import ConsentEvent
    events = (await db.execute(
        select(ConsentEvent)
        .where(ConsentEvent.contact_id == contact_id)
        .order_by(ConsentEvent.id.desc())
    )).scalars().all()
    return JSONResponse([
        {
            "category": e.category,
            "action": e.action,
            "business_name": e.business_name,
            "disclosure_text": e.disclosure_text,
            "source": e.source,
            "evidence": e.evidence,
            "proof_reference": e.proof_reference,
            "privacy_policy_url": e.privacy_policy_url,
            "actor": e.actor,
            "occurred_at": e.occurred_at.isoformat(),
            "recorded_at": e.created_at.isoformat(),
        }
        for e in events
    ])


@router.post("/{contact_id}/erase-data")
async def erase_contact_data(contact_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Fulfil a right-to-erasure request — permanently delete all data associated with this contact."""
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    contact = (await db.execute(select(Contact).where(Contact.id == contact_id))).scalar_one_or_none()
    if not contact:
        raise HTTPException(404, "Not found")

    from app.models.conversation import Conversation, Message
    from app.models.broadcast import BroadcastRecipient
    from app.models.drip_campaign import DripEnrollment
    from app.models.campaign_flow import CampaignFlowState
    from app.models.consent import ConsentEvent

    phone = contact.phone
    await log_event(db, actor=request.session.get("admin_email", "admin"), action="contact_data_erasure",
                     target_type="contact", target_id=contact.id, meta={"phone": phone})

    conv_ids = (await db.execute(
        select(Conversation.id).where(Conversation.contact_id == contact_id)
    )).scalars().all()
    if conv_ids:
        await db.execute(delete(Message).where(Message.conversation_id.in_(conv_ids)))
    await db.execute(delete(Conversation).where(Conversation.contact_id == contact_id))
    await db.execute(delete(BroadcastRecipient).where(BroadcastRecipient.contact_id == contact_id))
    await db.execute(delete(DripEnrollment).where(DripEnrollment.contact_id == contact_id))
    await db.execute(delete(CampaignFlowState).where(CampaignFlowState.contact_id == contact_id))
    await db.execute(delete(ConsentEvent).where(ConsentEvent.contact_id == contact_id))
    await db.execute(delete(Contact).where(Contact.id == contact_id))
    await db.commit()

    return JSONResponse({"status": "erased", "phone": phone})


@router.get("/export")
async def export_contacts(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return RedirectResponse("/login", status_code=302)
    contacts = (await db.execute(select(Contact).order_by(Contact.created_at))).scalars().all()
    lines = ["Phone,Name,Email,Tags,Verified Marketing Consent,Created"]
    for c in contacts:
        lines.append(f"{c.phone},{c.name or ''},{c.email or ''},{';'.join(c.tags or [])},{c.is_opted_in},{c.created_at.strftime('%Y-%m-%d')}")
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("\n".join(lines), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=contacts.csv"})
