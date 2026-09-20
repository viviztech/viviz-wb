from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select, update
from datetime import datetime
from slowapi import Limiter
from slowapi.util import get_remote_address
import logging

from app.database import get_db
from app.config import settings
from app.models.admin import Admin
from app.models.lead import Lead

logger = logging.getLogger(__name__)
from app.services.auth import (
    authenticate_admin,
    hash_password,
    password_strength_error,
    verify_password,
)
from app.models.password_reset import PasswordResetToken
from app.services.password_reset import (
    create_reset_token,
    get_valid_reset,
    send_password_reset_email,
)
from app.services.audit import log_event

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="app/templates")
limiter = Limiter(key_func=get_remote_address)


@router.get("/", response_class=HTMLResponse)
async def root(request: Request):
    if request.session.get("admin_email"):
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse("landing.html", {"request": request})


def _public_context(request: Request, legal_page: str) -> dict:
    return {
        "request": request,
        "legal_page": legal_page,
        "business_name": settings.business_name or "Viviz Technologies",
        "support_email": settings.support_email or "online@viviz.in",
        "support_phone": settings.support_phone or "+91 93440 64631",
        "business_address": (
            "2/13/3, Sri Sathyam Nagar, Lalgudi, Thalakudi, "
            "Tiruchirappalli - 621216, Tamil Nadu, India"
        ),
        "last_updated": "19 September 2026",
    }


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_policy(request: Request):
    return templates.TemplateResponse("legal.html", _public_context(request, "privacy"))


@router.get("/terms", response_class=HTMLResponse)
async def terms_and_conditions(request: Request):
    return templates.TemplateResponse("legal.html", _public_context(request, "terms"))


@router.get("/data-deletion", response_class=HTMLResponse)
async def data_deletion(request: Request):
    return templates.TemplateResponse("legal.html", _public_context(request, "data-deletion"))


@router.get("/support", response_class=HTMLResponse)
async def public_support(request: Request):
    return templates.TemplateResponse("legal.html", _public_context(request, "support"))


@router.post("/leads")
@limiter.limit("10/minute")
async def submit_lead(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(""),
    business_name: str = Form(...),
    phone: str = Form(...),
    email: str = Form(...),
    business_type: str = Form(""),
    volume: str = Form(""),
    message: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    phone = phone.strip().lstrip("+").replace(" ", "")
    if not phone.startswith("91"):
        phone = "91" + phone

    lead = Lead(
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        business_name=business_name.strip(),
        phone=phone,
        email=email.strip().lower(),
        business_type=business_type or None,
        volume=volume or None,
        message=message.strip() or None,
    )
    db.add(lead)
    await db.commit()
    logger.info(f"New lead: {first_name} {last_name} — {business_name} ({phone})")

    return templates.TemplateResponse("landing.html", {
        "request": request,
        "lead_success": True,
    })


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("admin_email"):
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse("dashboard/login.html", {
        "request": request,
        "reset_success": request.query_params.get("reset") == "success",
    })


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
    await log_event(db, actor=admin.email, action="admin_login", target_type="admin", target_id=admin.id)
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


@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    if request.session.get("admin_email"):
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(
        "dashboard/forgot_password.html",
        {"request": request},
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@router.post("/forgot-password", response_class=HTMLResponse)
@limiter.limit("3/hour")
async def forgot_password(
    request: Request,
    email: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    normalized_email = email.strip().lower()
    admin = (
        await db.execute(
            select(Admin).where(func.lower(Admin.email) == normalized_email, Admin.is_active == True)
        )
    ).scalar_one_or_none()

    if admin:
        token = await create_reset_token(
            db, admin, request.client.host if request.client else None
        )
        delivered = False
        try:
            await send_password_reset_email(admin, token)
            delivered = True
        except Exception:
            # Do not expose SMTP configuration or account existence publicly.
            logger.exception("Password reset email delivery failed")
            valid = await get_valid_reset(db, token, lock=True)
            if valid:
                valid[0].used_at = datetime.utcnow()
        await log_event(
            db,
            actor="system",
            action="password_reset_requested",
            target_type="admin",
            target_id=admin.id,
            meta={"email_delivered": delivered},
        )
    await db.commit()

    return templates.TemplateResponse(
        "dashboard/forgot_password.html",
        {
            "request": request,
            "success": (
                "If an active account matches that email and email delivery is configured, "
                "a password-reset link has been sent."
            ),
        },
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(
    request: Request,
    token: str = "",
    db: AsyncSession = Depends(get_db),
):
    valid = await get_valid_reset(db, token)
    return templates.TemplateResponse(
        "dashboard/reset_password.html",
        {"request": request, "token": token if valid else "", "invalid": not bool(valid)},
        status_code=200 if valid else 400,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@router.post("/reset-password", response_class=HTMLResponse)
@limiter.limit("10/minute")
async def reset_password(
    request: Request,
    token: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    def error_response(message: str, invalid: bool = False):
        return templates.TemplateResponse(
            "dashboard/reset_password.html",
            {"request": request, "token": "" if invalid else token, "error": message, "invalid": invalid},
            status_code=400,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    if new_password != confirm_password:
        return error_response("Passwords do not match.")
    strength_error = password_strength_error(new_password)
    if strength_error:
        return error_response(strength_error)

    valid = await get_valid_reset(db, token, lock=True)
    if not valid:
        return error_response("This reset link is invalid, expired, or has already been used.", True)

    reset, admin = valid
    now = datetime.utcnow()
    admin.password_hash = hash_password(new_password)
    admin.must_change_password = False
    reset.used_at = now
    await db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.admin_id == admin.id,
            PasswordResetToken.id != reset.id,
            PasswordResetToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    await log_event(
        db,
        actor=admin.email,
        action="password_reset_completed",
        target_type="admin",
        target_id=admin.id,
    )
    await db.commit()
    request.session.clear()
    return RedirectResponse("/login?reset=success", status_code=303)


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

    strength_error = password_strength_error(new_password)
    if strength_error:
        return err(strength_error)

    result = await db.execute(
        select(Admin).where(Admin.email == request.session["admin_email"])
    )
    admin = result.scalar_one_or_none()
    if not admin:
        return RedirectResponse("/login", status_code=302)

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
