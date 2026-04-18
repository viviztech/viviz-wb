from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.services.auth import authenticate_admin

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("admin_email"):
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse("dashboard/login.html", {"request": request})


@router.post("/login")
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
    request.session["admin_email"] = admin.email
    request.session["admin_name"] = admin.name
    return RedirectResponse("/dashboard", status_code=302)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)
