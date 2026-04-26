"""
MM Lite (Marketing Messages Lite) service.

MM Lite is Meta's optimized marketing message delivery channel.
- Same Cloud API templates and credentials — no new templates needed.
- Onboarding: Business Manager accepts Terms of Service via Embedded Signup;
  Meta fires a `tos_signed` webhook under the `marketing_messages` field.
- Send: uses Cloud API v3 messages endpoint — identical payload to Cloud API,
  but Meta routes it through their MM Lite delivery infrastructure when the
  WABA has accepted ToS.
- Analytics: subscribe to `marketing_messages` webhook field to receive
  delivery + conversion metrics specific to MM Lite.
"""

import urllib.parse
import httpx
import logging
from app.config import settings

logger = logging.getLogger(__name__)

# Meta's Embedded Signup base URL — businesses click this to accept MM Lite ToS.
_ES_BASE = "https://www.facebook.com/dialog/oauth"

# Permissions required for MM Lite (superset of standard Cloud API scopes).
_MM_LITE_SCOPES = [
    "whatsapp_business_management",
    "whatsapp_business_messaging",
    "business_management",
]

# Webhook fields that must be subscribed for MM Lite delivery + conversion metrics.
MM_LITE_WEBHOOK_FIELDS = [
    "messages",
    "marketing_messages",  # MM Lite delivery events + tos_signed
]


def build_embedded_signup_url(redirect_uri: str, state: str = "mm_lite_onboard") -> str:
    """
    Return the Embedded Signup URL the business owner must visit to accept
    MM Lite Terms of Service. After completion Meta fires a `tos_signed` webhook.
    """
    params = {
        "client_id": settings.meta_app_id,
        "redirect_uri": redirect_uri,
        "scope": ",".join(_MM_LITE_SCOPES),
        "response_type": "code",
        "state": state,
        # extras tell Meta this flow is for MM Lite ToS acceptance
        "extras": '{"feature":"marketing_messages_lite","setup":{}}',
    }
    return f"{_ES_BASE}?{urllib.parse.urlencode(params)}"


async def get_waba_mm_lite_status(waba_id: str) -> dict:
    """
    Query the Graph API for the current MM Lite status of a WABA.
    Returns the raw API response dict.
    """
    url = (
        f"{settings.whatsapp_api_url}/{waba_id}"
        f"?fields=id,marketing_messages_lite_status"
        f"&access_token={settings.whatsapp_access_token}"
    )
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.json()


async def subscribe_mm_lite_webhook(waba_id: str) -> dict:
    """
    Subscribe the app to the `marketing_messages` webhook field on this WABA.
    Must be called once after onboarding to start receiving MM Lite delivery events.
    """
    url = f"{settings.whatsapp_api_url}/{waba_id}/subscribed_apps"
    payload = {"subscribed_fields": ",".join(MM_LITE_WEBHOOK_FIELDS)}
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(url, json=payload, headers=headers)
        r.raise_for_status()
        return r.json()


async def send_mm_lite_template(
    to: str,
    template_name: str,
    language_code: str = "en",
    components: list | None = None,
    ttl_seconds: int | None = None,
) -> dict:
    """
    Send a marketing template via MM Lite.
    Payload is identical to Cloud API — Meta routes it through MM Lite when
    the WABA has completed ToS acceptance. Only MARKETING category templates
    are supported; other categories will be rejected by Meta.

    ttl_seconds: optional message TTL (12h–30d). When set, undelivered messages
    expire after this duration instead of Meta's default.
    """
    url = f"{settings.whatsapp_api_url}/{settings.whatsapp_phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
        "Content-Type": "application/json",
    }

    template_payload: dict = {
        "name": template_name,
        "language": {"code": language_code},
    }
    if components:
        template_payload["components"] = components

    payload: dict = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": template_payload,
    }

    # TTL support — MM Lite specific feature (12h to 30d)
    if ttl_seconds is not None:
        clamped = max(43200, min(ttl_seconds, 2592000))  # 12h … 30d
        payload["ttl"] = {"policy": "last_window", "duration_in_seconds": clamped}

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, json=payload, headers=headers)
        r.raise_for_status()
        return r.json()
