from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from app.database import get_db
from app.models.template import MessageTemplate
from app.services.whatsapp import whatsapp

router = APIRouter(prefix="/templates", tags=["templates"])
templates = Jinja2Templates(directory="app/templates")


def _auth(request: Request):
    return request.session.get("admin_email")


@router.get("", response_class=HTMLResponse)
async def templates_list(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return RedirectResponse("/login", status_code=302)

    # Sync from Meta
    try:
        meta_tpls = await whatsapp.list_templates()
        for t in meta_tpls.get("data", []):
            existing = (await db.execute(
                select(MessageTemplate).where(MessageTemplate.name == t.get("name"))
            )).scalar_one_or_none()
            if not existing:
                comp = {c["type"]: c for c in t.get("components", [])}
                body_comp = comp.get("BODY", {})
                header_comp = comp.get("HEADER", {})
                footer_comp = comp.get("FOOTER", {})
                tpl = MessageTemplate(
                    name=t.get("name"),
                    language=t.get("language", "en"),
                    category=t.get("category", "UTILITY"),
                    status=t.get("status", "PENDING"),
                    wa_template_id=t.get("id"),
                    header_type=header_comp.get("format", "").lower() or None,
                    header_content=header_comp.get("text"),
                    body=body_comp.get("text", ""),
                    footer=footer_comp.get("text"),
                )
                db.add(tpl)
            else:
                existing.status = t.get("status", existing.status)
        await db.commit()
    except Exception:
        pass

    tpls = (await db.execute(select(MessageTemplate).order_by(desc(MessageTemplate.created_at)))).scalars().all()
    return templates.TemplateResponse("dashboard/templates.html", {
        "request": request,
        "admin_name": request.session.get("admin_name", "Admin"),
        "templates": tpls,
        "page": "templates",
    })


@router.post("/create")
async def create_template(
    request: Request,
    name: str = Form(...),
    category: str = Form(...),
    language: str = Form("en"),
    body: str = Form(...),
    footer: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    tpl = MessageTemplate(
        name=name.lower().replace(" ", "_"),
        category=category,
        language=language,
        body=body,
        footer=footer,
        status="PENDING",
    )
    db.add(tpl)
    await db.flush()
    return JSONResponse({"status": "created", "id": tpl.id})


@router.delete("/{tpl_id}")
async def delete_template(tpl_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    tpl = (await db.execute(select(MessageTemplate).where(MessageTemplate.id == tpl_id))).scalar_one_or_none()
    if tpl:
        await db.delete(tpl)
    return JSONResponse({"status": "deleted"})
