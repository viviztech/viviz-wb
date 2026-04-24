from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.auto_reply import AutoReply
from app.models.template import MessageTemplate

router = APIRouter(prefix="/auto-replies", tags=["auto_replies"])
templates = Jinja2Templates(directory="app/templates")


def _auth(request: Request):
    return request.session.get("admin_email")


@router.get("", response_class=HTMLResponse)
async def list_auto_replies(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return RedirectResponse("/login", status_code=302)
    rules = (await db.execute(
        select(AutoReply).order_by(AutoReply.priority.desc(), AutoReply.id)
    )).scalars().all()
    approved_tpls = (await db.execute(
        select(MessageTemplate).where(MessageTemplate.status == "APPROVED")
    )).scalars().all()
    return templates.TemplateResponse("dashboard/auto_replies.html", {
        "request": request,
        "admin_name": request.session.get("admin_name", "Admin"),
        "rules": rules,
        "approved_templates": approved_tpls,
        "page": "auto_replies",
    })


@router.post("/create")
async def create_rule(
    request: Request,
    keyword: str = Form(...),
    match_type: str = Form("contains"),
    template_name: str = Form(""),
    reply_text: str = Form(""),
    priority: int = Form(0),
    db: AsyncSession = Depends(get_db),
):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    if not template_name and not reply_text:
        return JSONResponse({"error": "Provide either a template or reply text"}, status_code=400)

    rule = AutoReply(
        keyword=keyword.strip().lower(),
        match_type=match_type,
        template_name=template_name or None,
        reply_text=reply_text or None,
        priority=priority,
    )
    db.add(rule)
    await db.commit()
    return JSONResponse({"status": "created", "id": rule.id})


@router.post("/{rule_id}/toggle")
async def toggle_rule(rule_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    rule = (await db.execute(select(AutoReply).where(AutoReply.id == rule_id))).scalar_one_or_none()
    if not rule:
        return JSONResponse({"error": "Not found"}, status_code=404)
    rule.is_active = not rule.is_active
    await db.commit()
    return JSONResponse({"status": "active" if rule.is_active else "inactive"})


@router.delete("/{rule_id}")
async def delete_rule(rule_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    rule = (await db.execute(select(AutoReply).where(AutoReply.id == rule_id))).scalar_one_or_none()
    if rule:
        await db.delete(rule)
        await db.commit()
    return JSONResponse({"status": "deleted"})
