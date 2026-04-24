from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from app.database import get_db
from app.models.campaign_flow import CampaignFlow, CampaignFlowStep, CampaignFlowState
from app.models.template import MessageTemplate
import logging

router = APIRouter(prefix="/campaign-flows", tags=["campaign_flows"])
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)


def _auth(r): return r.session.get("admin_email")


@router.get("", response_class=HTMLResponse)
async def list_flows(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return RedirectResponse("/login", status_code=302)
    flows = (await db.execute(select(CampaignFlow).order_by(desc(CampaignFlow.created_at)))).scalars().all()
    approved_tpls = (await db.execute(
        select(MessageTemplate).where(MessageTemplate.status == "APPROVED", MessageTemplate.name != "hello_world")
    )).scalars().all()
    from sqlalchemy import func
    active_counts = {}
    rows = (await db.execute(
        select(CampaignFlowState.flow_id, func.count(CampaignFlowState.id))
        .where(CampaignFlowState.status == "active")
        .group_by(CampaignFlowState.flow_id)
    )).fetchall()
    for fid, cnt in rows:
        active_counts[fid] = cnt
    return templates.TemplateResponse("dashboard/campaign_flows.html", {
        "request": request,
        "admin_name": request.session.get("admin_name", "Admin"),
        "flows": flows,
        "approved_templates": approved_tpls,
        "active_counts": active_counts,
        "page": "campaign_flows",
    })


@router.post("/create")
async def create_flow(
    request: Request,
    name: str = Form(...),
    trigger_keyword: str = Form(...),
    match_type: str = Form("contains"),
    db: AsyncSession = Depends(get_db),
):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    flow = CampaignFlow(name=name, trigger_keyword=trigger_keyword.strip().lower(), match_type=match_type)
    db.add(flow)
    await db.commit()
    return JSONResponse({"status": "created", "id": flow.id})


@router.post("/{flow_id}/steps/add")
async def add_step(
    flow_id: int,
    request: Request,
    step_order: int = Form(...),
    template_name: str = Form(""),
    message: str = Form(""),
    wait_for_reply: str = Form("false"),
    reply_keyword: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    step = CampaignFlowStep(
        flow_id=flow_id,
        step_order=step_order,
        template_name=template_name or None,
        message=message or None,
        wait_for_reply=wait_for_reply == "true",
        reply_keyword=reply_keyword.strip().lower() or None,
    )
    db.add(step)
    await db.commit()
    return JSONResponse({"status": "added", "id": step.id})


@router.delete("/{flow_id}/steps/{step_id}")
async def delete_step(flow_id: int, step_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    step = (await db.execute(select(CampaignFlowStep).where(CampaignFlowStep.id == step_id))).scalar_one_or_none()
    if step:
        await db.delete(step)
        await db.commit()
    return JSONResponse({"status": "deleted"})


@router.get("/{flow_id}/steps")
async def get_steps(flow_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    steps = (await db.execute(
        select(CampaignFlowStep).where(CampaignFlowStep.flow_id == flow_id).order_by(CampaignFlowStep.step_order)
    )).scalars().all()
    return JSONResponse([{
        "id": s.id, "step_order": s.step_order, "template_name": s.template_name,
        "message": s.message, "wait_for_reply": s.wait_for_reply, "reply_keyword": s.reply_keyword,
    } for s in steps])


@router.post("/{flow_id}/toggle")
async def toggle_flow(flow_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    flow = (await db.execute(select(CampaignFlow).where(CampaignFlow.id == flow_id))).scalar_one_or_none()
    if not flow:
        return JSONResponse({"error": "Not found"}, status_code=404)
    flow.is_active = not flow.is_active
    await db.commit()
    return JSONResponse({"status": "active" if flow.is_active else "inactive"})


@router.delete("/{flow_id}")
async def delete_flow(flow_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    flow = (await db.execute(select(CampaignFlow).where(CampaignFlow.id == flow_id))).scalar_one_or_none()
    if flow:
        await db.delete(flow)
        await db.commit()
    return JSONResponse({"status": "deleted"})
