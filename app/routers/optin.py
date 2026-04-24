"""
Public opt-in page — generates a WhatsApp deep-link QR code.
No auth required (it's a public landing page for customers).
"""
import io
import base64
import qrcode
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from app.config import settings

router = APIRouter(prefix="/optin", tags=["optin"])
templates = Jinja2Templates(directory="app/templates")


def _wa_deeplink(phone: str, message: str) -> str:
    from urllib.parse import quote
    clean = phone.replace("+", "").replace(" ", "")
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
    phone: str = Query(default=""),
    message: str = Query(default="Hi! I'd like to know more about your services."),
):
    # Use configured phone number if none provided
    wa_phone = phone or settings.whatsapp_phone_number_id
    deeplink = _wa_deeplink(wa_phone, message)
    qr_img = _qr_base64(deeplink)

    return templates.TemplateResponse("optin.html", {
        "request": request,
        "deeplink": deeplink,
        "qr_img": qr_img,
        "wa_phone": wa_phone,
        "pre_message": message,
    })


@router.get("/qr.png")
async def qr_image(
    phone: str = Query(default=""),
    message: str = Query(default="Hi! I'd like to know more about your services."),
):
    """Returns raw QR PNG — embed as <img src='/optin/qr.png'> on any page."""
    wa_phone = phone or settings.whatsapp_phone_number_id
    deeplink = _wa_deeplink(wa_phone, message)

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
