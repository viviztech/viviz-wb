"""Meta Marketing Messages API service.

Meta renamed Marketing Messages Lite to the Marketing Messages API. Businesses
accept the product terms in the Meta App Dashboard, send MARKETING templates to
the dedicated ``/marketing_messages`` endpoint, and receive delivery state on
the normal ``messages`` webhook.
"""

import httpx

from app.config import settings


# Marketing Messages delivery events arrive through the standard messages
# subscription. There is no separate ``marketing_messages`` webhook field.
MARKETING_MESSAGES_WEBHOOK_FIELDS = ["messages"]


def meta_app_dashboard_url() -> str:
    """Return the official dashboard entry point used to accept the terms."""
    if settings.meta_app_id:
        return f"https://developers.facebook.com/apps/{settings.meta_app_id}/"
    return "https://developers.facebook.com/apps/"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
        "Content-Type": "application/json",
    }


async def get_marketing_api_readiness() -> dict:
    """Validate the configured phone-number ID and access token.

    Meta does not expose a ``marketing_messages_lite_status`` field. Product
    eligibility is confirmed by an actual send and its status webhook. This
    request only verifies that the required Graph credentials are usable.
    """
    phone_id = settings.whatsapp_phone_number_id
    if not phone_id:
        raise ValueError("WhatsApp phone number ID is not configured")
    url = f"{settings.whatsapp_api_url}/{phone_id}"
    params = {"fields": "id,display_phone_number,quality_rating"}
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(url, params=params, headers=_headers())
        response.raise_for_status()
        return response.json()


async def subscribe_marketing_webhook(waba_id: str) -> dict:
    """Subscribe the app to standard message and message-status webhooks."""
    if not waba_id:
        raise ValueError("WhatsApp Business Account ID is not configured")
    url = f"{settings.whatsapp_api_url}/{waba_id}/subscribed_apps"
    payload = {"subscribed_fields": ",".join(MARKETING_MESSAGES_WEBHOOK_FIELDS)}
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(url, json=payload, headers=_headers())
        response.raise_for_status()
        return response.json()


async def send_marketing_template(
    to: str,
    template_name: str,
    language_code: str = "en",
    components: list | None = None,
) -> dict:
    """Send an approved MARKETING template via Meta's dedicated endpoint."""
    phone_id = settings.whatsapp_phone_number_id
    if not phone_id:
        raise ValueError("WhatsApp phone number ID is not configured")
    url = f"{settings.whatsapp_api_url}/{phone_id}/marketing_messages"

    template_payload: dict = {
        "name": template_name,
        "language": {"code": language_code},
    }
    if components:
        template_payload["components"] = components

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "template",
        "template": template_payload,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(url, json=payload, headers=_headers())
        response.raise_for_status()
        return response.json()


# Compatibility aliases for older imports while deployments roll forward.
get_waba_mm_lite_status = get_marketing_api_readiness
subscribe_mm_lite_webhook = subscribe_marketing_webhook
send_mm_lite_template = send_marketing_template
