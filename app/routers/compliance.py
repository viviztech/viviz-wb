from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from app.database import get_db
from app.models.audit import AuditLog

router = APIRouter(prefix="/compliance", tags=["compliance"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/audit-logs", response_class=HTMLResponse)
async def audit_logs_page(
    request: Request,
    page: int = 1,
    action: str = "",
    db: AsyncSession = Depends(get_db),
):
    """Immutable compliance audit trail — opt-in/opt-out changes, admin logins, broadcast sends, data privacy requests."""
    if not request.session.get("admin_email"):
        return RedirectResponse("/login", status_code=302)

    per_page = 50
    offset = (max(1, page) - 1) * per_page

    query = select(AuditLog).order_by(desc(AuditLog.created_at))
    count_q = select(func.count(AuditLog.id))
    if action:
        query = query.where(AuditLog.action == action)
        count_q = count_q.where(AuditLog.action == action)

    total = (await db.execute(count_q)).scalar()
    total_pages = max(1, (total + per_page - 1) // per_page)
    logs = (await db.execute(query.offset(offset).limit(per_page))).scalars().all()

    actions_result = await db.execute(select(AuditLog.action).distinct().order_by(AuditLog.action))
    actions = [r[0] for r in actions_result.fetchall() if r[0]]

    return templates.TemplateResponse("dashboard/audit_logs.html", {
        "request": request,
        "admin_name": request.session.get("admin_name", "Admin"),
        "logs": logs,
        "page": "audit_logs",
        "current_page": page,
        "total_pages": total_pages,
        "total": total,
        "action_filter": action,
        "actions": actions,
    })
