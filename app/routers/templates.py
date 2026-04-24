from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from app.database import get_db
from app.models.template import MessageTemplate
from app.services.whatsapp import whatsapp
import logging

router = APIRouter(prefix="/templates", tags=["templates"])
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)


def _auth(request: Request):
    return request.session.get("admin_email")


@router.get("", response_class=HTMLResponse)
async def templates_list(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return RedirectResponse("/login", status_code=302)

    # Sync status updates from Meta
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
                if t.get("id") and not existing.wa_template_id:
                    existing.wa_template_id = t.get("id")
        await db.commit()
    except Exception as ex:
        logger.warning(f"Meta template sync failed: {ex}")

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
    header: str = Form(""),
    body: str = Form(...),
    footer: str = Form(""),
    submit_to_meta: str = Form("false"),
    db: AsyncSession = Depends(get_db),
):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    clean_name = name.lower().replace(" ", "_")

    existing = (await db.execute(
        select(MessageTemplate).where(MessageTemplate.name == clean_name)
    )).scalar_one_or_none()
    if existing:
        return JSONResponse({"error": f"Template '{clean_name}' already exists"}, status_code=400)

    tpl = MessageTemplate(
        name=clean_name,
        category=category,
        language=language,
        header_type="text" if header else None,
        header_content=header or None,
        body=body,
        footer=footer,
        status="PENDING",
    )
    db.add(tpl)
    await db.flush()

    if submit_to_meta == "true":
        try:
            components = []
            if header:
                components.append({"type": "HEADER", "format": "TEXT", "text": header})
            components.append({"type": "BODY", "text": body})
            if footer:
                components.append({"type": "FOOTER", "text": footer})

            result = await whatsapp.create_template(
                name=clean_name,
                language=language,
                category=category,
                components=components,
            )
            tpl.wa_template_id = result.get("id")
            tpl.status = result.get("status", "PENDING")
            await db.commit()
            return JSONResponse({
                "status": "submitted",
                "id": tpl.id,
                "wa_id": tpl.wa_template_id,
                "meta_status": tpl.status,
            })
        except Exception as ex:
            await db.commit()
            logger.error(f"Meta template submission failed: {ex}")
            return JSONResponse({"error": f"Saved locally but Meta submission failed: {str(ex)}"}, status_code=422)

    await db.commit()
    return JSONResponse({"status": "created", "id": tpl.id})


@router.post("/{tpl_id}/submit")
async def submit_template_to_meta(tpl_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Submit an existing local draft template to Meta for approval."""
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    tpl = (await db.execute(select(MessageTemplate).where(MessageTemplate.id == tpl_id))).scalar_one_or_none()
    if not tpl:
        return JSONResponse({"error": "Template not found"}, status_code=404)
    if tpl.wa_template_id:
        return JSONResponse({"error": "Already submitted to Meta"}, status_code=400)

    try:
        components = []
        if tpl.header_content:
            components.append({"type": "HEADER", "format": "TEXT", "text": tpl.header_content})
        components.append({"type": "BODY", "text": tpl.body})
        if tpl.footer:
            components.append({"type": "FOOTER", "text": tpl.footer})

        result = await whatsapp.create_template(
            name=tpl.name,
            language=tpl.language,
            category=tpl.category,
            components=components,
        )
        tpl.wa_template_id = result.get("id")
        tpl.status = result.get("status", "PENDING")
        await db.commit()
        return JSONResponse({"status": "submitted", "wa_id": tpl.wa_template_id, "meta_status": tpl.status})
    except Exception as ex:
        logger.error(f"Meta template submit error: {ex}")
        return JSONResponse({"error": str(ex)}, status_code=422)


@router.delete("/{tpl_id}")
async def delete_template(tpl_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    tpl = (await db.execute(select(MessageTemplate).where(MessageTemplate.id == tpl_id))).scalar_one_or_none()
    if tpl:
        await db.delete(tpl)
        await db.commit()
    return JSONResponse({"status": "deleted"})
