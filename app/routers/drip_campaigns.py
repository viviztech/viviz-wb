from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from datetime import datetime, timedelta
from app.database import get_db
from app.models.drip_campaign import DripCampaign, DripStep, DripEnrollment
from app.models.contact import Contact
from app.models.template import MessageTemplate
import logging

router = APIRouter(prefix="/drip-campaigns", tags=["drip_campaigns"])
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)


def _auth(r): return r.session.get("admin_email")


@router.get("", response_class=HTMLResponse)
async def list_campaigns(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return RedirectResponse("/login", status_code=302)
    campaigns = (await db.execute(select(DripCampaign).order_by(desc(DripCampaign.created_at)))).scalars().all()
    approved_tpls = (await db.execute(
        select(MessageTemplate).where(MessageTemplate.status == "APPROVED", MessageTemplate.name != "hello_world")
    )).scalars().all()
    # Enrollment counts per campaign
    from sqlalchemy import func
    counts = {}
    rows = (await db.execute(
        select(DripEnrollment.campaign_id, func.count(DripEnrollment.id))
        .where(DripEnrollment.status == "active")
        .group_by(DripEnrollment.campaign_id)
    )).fetchall()
    for cid, cnt in rows:
        counts[cid] = cnt
    return templates.TemplateResponse("dashboard/drip_campaigns.html", {
        "request": request,
        "admin_name": request.session.get("admin_name", "Admin"),
        "campaigns": campaigns,
        "approved_templates": approved_tpls,
        "enrollment_counts": counts,
        "page": "drip_campaigns",
    })


@router.post("/create")
async def create_campaign(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    trigger_tag: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    c = DripCampaign(name=name, description=description or None, trigger_tag=trigger_tag or None)
    db.add(c)
    await db.commit()
    return JSONResponse({"status": "created", "id": c.id})


@router.post("/{campaign_id}/steps/add")
async def add_step(
    campaign_id: int,
    request: Request,
    step_order: int = Form(...),
    delay_days: int = Form(0),
    delay_hours: int = Form(0),
    template_name: str = Form(""),
    message: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    step = DripStep(
        campaign_id=campaign_id,
        step_order=step_order,
        delay_days=delay_days,
        delay_hours=delay_hours,
        template_name=template_name or None,
        message=message or None,
    )
    db.add(step)
    await db.commit()
    return JSONResponse({"status": "added", "id": step.id})


@router.delete("/{campaign_id}/steps/{step_id}")
async def delete_step(campaign_id: int, step_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    step = (await db.execute(select(DripStep).where(DripStep.id == step_id, DripStep.campaign_id == campaign_id))).scalar_one_or_none()
    if step:
        await db.delete(step)
        await db.commit()
    return JSONResponse({"status": "deleted"})


@router.post("/{campaign_id}/enroll")
async def enroll_contacts(
    campaign_id: int,
    request: Request,
    tags: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    campaign = (await db.execute(select(DripCampaign).where(DripCampaign.id == campaign_id))).scalar_one_or_none()
    if not campaign:
        return JSONResponse({"error": "Campaign not found"}, status_code=404)

    # Get first step to calculate next_send_at
    first_step = (await db.execute(
        select(DripStep).where(DripStep.campaign_id == campaign_id).order_by(DripStep.step_order).limit(1)
    )).scalar_one_or_none()
    if not first_step:
        return JSONResponse({"error": "Campaign has no steps"}, status_code=400)

    query = select(Contact).where(Contact.is_opted_in == True, Contact.is_blocked == False)
    contacts = (await db.execute(query)).scalars().all()
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    if tag_list:
        contacts = [c for c in contacts if any(t in (c.tags or []) for t in tag_list)]

    enrolled = 0
    now = datetime.utcnow()
    for contact in contacts:
        existing = (await db.execute(
            select(DripEnrollment).where(
                DripEnrollment.campaign_id == campaign_id,
                DripEnrollment.contact_id == contact.id,
                DripEnrollment.status == "active",
            )
        )).scalar_one_or_none()
        if existing:
            continue
        next_send = now + timedelta(days=first_step.delay_days, hours=first_step.delay_hours)
        db.add(DripEnrollment(
            campaign_id=campaign_id,
            contact_id=contact.id,
            current_step=first_step.step_order,
            next_send_at=next_send,
        ))
        enrolled += 1
    await db.commit()
    return JSONResponse({"enrolled": enrolled})


@router.post("/{campaign_id}/toggle")
async def toggle_campaign(campaign_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    c = (await db.execute(select(DripCampaign).where(DripCampaign.id == campaign_id))).scalar_one_or_none()
    if not c:
        return JSONResponse({"error": "Not found"}, status_code=404)
    c.is_active = not c.is_active
    await db.commit()
    return JSONResponse({"status": "active" if c.is_active else "inactive"})


@router.delete("/{campaign_id}")
async def delete_campaign(campaign_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    c = (await db.execute(select(DripCampaign).where(DripCampaign.id == campaign_id))).scalar_one_or_none()
    if c:
        await db.delete(c)
        await db.commit()
    return JSONResponse({"status": "deleted"})


@router.get("/{campaign_id}/steps")
async def get_steps(campaign_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    steps = (await db.execute(
        select(DripStep).where(DripStep.campaign_id == campaign_id).order_by(DripStep.step_order)
    )).scalars().all()
    return JSONResponse([{
        "id": s.id, "step_order": s.step_order, "delay_days": s.delay_days,
        "delay_hours": s.delay_hours, "template_name": s.template_name, "message": s.message,
    } for s in steps])
