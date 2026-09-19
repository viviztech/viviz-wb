from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from app.database import get_db
from app.models.template import MessageTemplate
from app.services.whatsapp import whatsapp
from app.services.template_builder import components_from_template, prepare_template
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
                buttons_comp = comp.get("BUTTONS", {})
                body_examples = body_comp.get("example", {}).get("body_text", [[]])
                body_values = body_examples[0] if body_examples and isinstance(body_examples[0], list) else []
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
                    buttons=buttons_comp.get("buttons", []),
                    variables=[
                        {"position": index + 1, "sample": value}
                        for index, value in enumerate(body_values)
                    ],
                )
                db.add(tpl)
            else:
                existing.status = t.get("status", existing.status)
                existing.category = t.get("category", existing.category)
                existing.language = t.get("language", existing.language)
                comp = {c["type"]: c for c in t.get("components", [])}
                if comp.get("BODY"):
                    existing.body = comp["BODY"].get("text", existing.body)
                    examples = comp["BODY"].get("example", {}).get("body_text", [[]])
                    values = examples[0] if examples and isinstance(examples[0], list) else []
                    existing.variables = [
                        {"position": index + 1, "sample": value}
                        for index, value in enumerate(values)
                    ]
                if comp.get("HEADER"):
                    existing.header_type = comp["HEADER"].get("format", "").lower() or None
                    existing.header_content = comp["HEADER"].get("text")
                if comp.get("FOOTER"):
                    existing.footer = comp["FOOTER"].get("text", existing.footer)
                existing.buttons = comp.get("BUTTONS", {}).get("buttons", existing.buttons or [])
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
    header_type: str = Form("NONE"),
    header_text: str = Form(""),
    body: str = Form(...),
    footer: str = Form(""),
    body_examples_json: str = Form("[]"),
    buttons_json: str = Form("[]"),
    submit_to_meta: str = Form("false"),
    db: AsyncSession = Depends(get_db),
):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        prepared = prepare_template(
            name=name,
            category=category,
            language=language,
            header_type=header_type,
            header_text=header_text,
            body=body,
            footer=footer,
            body_examples_json=body_examples_json,
            buttons_json=buttons_json,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    clean_name = prepared["name"]

    existing = (await db.execute(
        select(MessageTemplate).where(MessageTemplate.name == clean_name)
    )).scalar_one_or_none()
    if existing:
        return JSONResponse({"error": f"Template '{clean_name}' already exists"}, status_code=400)

    tpl = MessageTemplate(
        name=clean_name,
        category=prepared["category"],
        language=prepared["language"],
        header_type=prepared["header_type"],
        header_content=prepared["header_content"],
        body=prepared["body"],
        footer=prepared["footer"],
        buttons=prepared["buttons"],
        variables=prepared["variables"],
        status="DRAFT",
    )
    db.add(tpl)
    await db.flush()

    if submit_to_meta == "true":
        try:
            result = await whatsapp.create_template(
                name=clean_name,
                language=prepared["language"],
                category=prepared["category"],
                components=prepared["components"],
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
        result = await whatsapp.create_template(
            name=tpl.name,
            language=tpl.language,
            category=tpl.category,
            components=components_from_template(tpl),
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
