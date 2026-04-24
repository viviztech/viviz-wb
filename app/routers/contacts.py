from fastapi import APIRouter, Request, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, or_
from app.database import get_db
from app.models.contact import Contact
import csv, io

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

    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    contact = Contact(phone=phone, name=name, email=email, tags=tag_list, notes=notes)
    db.add(contact)
    await db.flush()
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
    db: AsyncSession = Depends(get_db),
):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    contact = (await db.execute(select(Contact).where(Contact.id == contact_id))).scalar_one_or_none()
    if not contact:
        raise HTTPException(404, "Not found")
    contact.name = name
    contact.email = email
    contact.tags = [t.strip() for t in tags.split(",") if t.strip()]
    contact.notes = notes
    contact.is_opted_in = is_opted_in.lower() == "true"
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

        db.add(Contact(phone=phone, name=name, email=email, tags=tag_list, notes=notes))
        added += 1

    await db.commit()
    return JSONResponse({"added": added, "skipped": skipped, "errors": errors[:10]})


@router.get("/export")
async def export_contacts(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return RedirectResponse("/login", status_code=302)
    contacts = (await db.execute(select(Contact).order_by(Contact.created_at))).scalars().all()
    lines = ["Phone,Name,Email,Tags,Opted In,Created"]
    for c in contacts:
        lines.append(f"{c.phone},{c.name or ''},{c.email or ''},{';'.join(c.tags or [])},{c.is_opted_in},{c.created_at.strftime('%Y-%m-%d')}")
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("\n".join(lines), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=contacts.csv"})
