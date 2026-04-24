from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.quick_reply import QuickReply

router = APIRouter(prefix="/quick-replies", tags=["quick_replies"])
templates = Jinja2Templates(directory="app/templates")


def _auth(request: Request):
    return request.session.get("admin_email")


@router.get("", response_class=HTMLResponse)
async def list_quick_replies(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return RedirectResponse("/login", status_code=302)
    qrs = (await db.execute(select(QuickReply).order_by(QuickReply.title))).scalars().all()
    return templates.TemplateResponse("dashboard/quick_replies.html", {
        "request": request,
        "admin_name": request.session.get("admin_name", "Admin"),
        "quick_replies": qrs,
        "page": "quick_replies",
    })


@router.get("/api", response_class=JSONResponse)
async def api_list(request: Request, db: AsyncSession = Depends(get_db)):
    """Used by chat UI to load quick replies."""
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    qrs = (await db.execute(select(QuickReply).order_by(QuickReply.title))).scalars().all()
    return [{"id": q.id, "title": q.title, "shortcut": q.shortcut, "message": q.message} for q in qrs]


@router.post("/create")
async def create_quick_reply(
    request: Request,
    title: str = Form(...),
    shortcut: str = Form(""),
    message: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    shortcut_clean = shortcut.strip().lstrip("/") or None
    if shortcut_clean:
        existing = (await db.execute(
            select(QuickReply).where(QuickReply.shortcut == shortcut_clean)
        )).scalar_one_or_none()
        if existing:
            return JSONResponse({"error": f"Shortcut '/{shortcut_clean}' already exists"}, status_code=400)

    qr = QuickReply(title=title.strip(), shortcut=shortcut_clean, message=message.strip())
    db.add(qr)
    await db.commit()
    return JSONResponse({"status": "created", "id": qr.id})


@router.post("/{qr_id}/update")
async def update_quick_reply(
    qr_id: int,
    request: Request,
    title: str = Form(...),
    shortcut: str = Form(""),
    message: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    qr = (await db.execute(select(QuickReply).where(QuickReply.id == qr_id))).scalar_one_or_none()
    if not qr:
        return JSONResponse({"error": "Not found"}, status_code=404)

    shortcut_clean = shortcut.strip().lstrip("/") or None
    if shortcut_clean and shortcut_clean != qr.shortcut:
        existing = (await db.execute(
            select(QuickReply).where(QuickReply.shortcut == shortcut_clean)
        )).scalar_one_or_none()
        if existing:
            return JSONResponse({"error": f"Shortcut '/{shortcut_clean}' already in use"}, status_code=400)

    qr.title = title.strip()
    qr.shortcut = shortcut_clean
    qr.message = message.strip()
    await db.commit()
    return JSONResponse({"status": "updated"})


@router.delete("/{qr_id}")
async def delete_quick_reply(qr_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    qr = (await db.execute(select(QuickReply).where(QuickReply.id == qr_id))).scalar_one_or_none()
    if qr:
        await db.delete(qr)
        await db.commit()
    return JSONResponse({"status": "deleted"})
