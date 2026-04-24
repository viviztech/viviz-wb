from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.database import get_db
from app.models.admin import Admin
from app.services.auth import authenticate_admin, hash_password

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="app/templates")
limiter = Limiter(key_func=get_remote_address)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("admin_email"):
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse("dashboard/login.html", {"request": request})


@router.post("/login")
@limiter.limit("10/minute")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    admin = await authenticate_admin(email, password, db)
    if not admin:
        return templates.TemplateResponse(
            "dashboard/login.html",
            {"request": request, "error": "Invalid email or password"},
            status_code=401,
        )
    await db.commit()
    request.session["admin_email"] = admin.email
    request.session["admin_name"] = admin.name
    if admin.must_change_password:
        return RedirectResponse("/change-password", status_code=302)
    return RedirectResponse("/dashboard", status_code=302)


@router.get("/change-password", response_class=HTMLResponse)
async def change_password_page(request: Request):
    if not request.session.get("admin_email"):
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse("dashboard/change_password.html", {"request": request})


@router.post("/change-password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if not request.session.get("admin_email"):
        return RedirectResponse("/login", status_code=302)

    def err(msg):
        return templates.TemplateResponse(
            "dashboard/change_password.html",
            {"request": request, "error": msg},
            status_code=400,
        )

    if new_password != confirm_password:
        return err("New passwords do not match.")

    if len(new_password) < 8:
        return err("Password must be at least 8 characters.")

    has_upper = any(c.isupper() for c in new_password)
    has_digit = any(c.isdigit() for c in new_password)
    if not has_upper or not has_digit:
        return err("Password must contain at least one uppercase letter and one number.")

    result = await db.execute(
        select(Admin).where(Admin.email == request.session["admin_email"])
    )
    admin = result.scalar_one_or_none()
    if not admin:
        return RedirectResponse("/login", status_code=302)

    from app.services.auth import verify_password
    if not verify_password(current_password, admin.password_hash):
        return err("Current password is incorrect.")

    admin.password_hash = hash_password(new_password)
    admin.must_change_password = False
    await db.commit()

    return templates.TemplateResponse(
        "dashboard/change_password.html",
        {"request": request, "success": "Password changed successfully!"},
    )


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)
