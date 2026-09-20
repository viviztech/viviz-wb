"""
Public opt-in page — generates a WhatsApp deep-link QR code.
No auth required (it's a public landing page for customers).
"""
import io
import base64
import re
import time
import logging
import qrcode
from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from app.config import settings
from app.services.consent import default_disclosure
from app.services.whatsapp import whatsapp

router = APIRouter(prefix="/optin", tags=["optin"])
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)

_phone_cache: tuple[str, float] = ("", 0.0)


def _phone_digits(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def _valid_customer_phone(phone: str) -> bool:
    digits = _phone_digits(phone)
    phone_number_id = _phone_digits(settings.whatsapp_phone_number_id)
    return 7 <= len(digits) <= 15 and digits != phone_number_id


async def _resolve_business_phone() -> str:
    """Use a valid configured number, otherwise resolve the display number from Meta."""
    global _phone_cache
    configured = settings.whatsapp_business_phone
    if _valid_customer_phone(configured):
        return configured

    cached_phone, expires_at = _phone_cache
    if _valid_customer_phone(cached_phone) and expires_at > time.monotonic():
        return cached_phone

    try:
        display_phone = await whatsapp.get_display_phone_number()
    except Exception as exc:
        fallback_phone = settings.support_phone
        if _valid_customer_phone(fallback_phone):
            logger.warning(
                "Meta display-number lookup failed; using the configured support phone for opt-in",
                exc_info=exc,
            )
            _phone_cache = (fallback_phone, time.monotonic() + 600)
            return fallback_phone
        raise HTTPException(
            503,
            "WhatsApp opt-in is temporarily unavailable. Please contact support.",
        ) from exc
    if not _valid_customer_phone(display_phone):
        fallback_phone = settings.support_phone
        if _valid_customer_phone(fallback_phone):
            logger.warning("Meta returned an invalid display number; using the configured support phone")
            _phone_cache = (fallback_phone, time.monotonic() + 600)
            return fallback_phone
        raise HTTPException(503, "WhatsApp opt-in is temporarily unavailable. Please contact support.")
    _phone_cache = (display_phone, time.monotonic() + 600)
    return display_phone


def _wa_deeplink(phone: str, message: str) -> str:
    from urllib.parse import quote
    clean = _phone_digits(phone)
    return f"https://wa.me/{clean}?text={quote(message)}"


def _qr_base64(url: str) -> str:
    qr = qrcode.QRCode(version=1, box_size=8, border=3,
                       error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#075E54", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


@router.get("", response_class=HTMLResponse)
async def optin_page(
    request: Request,
    category: str = Query(default="marketing"),
):
    if category not in {"marketing", "utility"}:
        raise HTTPException(400, "Category must be marketing or utility")
    wa_phone = await _resolve_business_phone()
    command = "CONFIRM MARKETING" if category == "marketing" else "CONFIRM UPDATES"
    deeplink = _wa_deeplink(wa_phone, command)
    qr_img = _qr_base64(deeplink)

    return templates.TemplateResponse("optin.html", {
        "request": request,
        "deeplink": deeplink,
        "qr_img": qr_img,
        "wa_phone": wa_phone,
        "pre_message": command,
        "disclosure": default_disclosure(category),
        "category": category,
        "privacy_policy_url": settings.privacy_policy_url,
        "support_email": settings.support_email,
    })


@router.get("/qr.png")
async def qr_image(
    category: str = Query(default="marketing"),
):
    """Returns raw QR PNG — embed as <img src='/optin/qr.png'> on any page."""
    if category not in {"marketing", "utility"}:
        raise HTTPException(400, "Category must be marketing or utility")
    wa_phone = await _resolve_business_phone()
    command = "CONFIRM MARKETING" if category == "marketing" else "CONFIRM UPDATES"
    deeplink = _wa_deeplink(wa_phone, command)

    qr = qrcode.QRCode(version=1, box_size=8, border=3,
                       error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(deeplink)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#075E54", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(content=buf.read(), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})
