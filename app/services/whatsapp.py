import httpx
from typing import Optional
from app.config import settings


class WhatsAppService:
    """Official Meta WhatsApp Cloud API client."""

    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {settings.whatsapp_access_token}",
            "Content-Type": "application/json",
        }

    async def _post(self, url: str, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(url, json=payload, headers=self.headers)
            r.raise_for_status()
            return r.json()

    async def _get(self, url: str) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url, headers=self.headers)
            r.raise_for_status()
            return r.json()

    # ── Text Message ──────────────────────────────────────────────────────────

    async def send_text(self, to: str, body: str, preview_url: bool = False) -> dict:
        return await self._post(settings.messages_url, {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": preview_url, "body": body},
        })

    # ── Template Message ──────────────────────────────────────────────────────

    async def send_template(
        self,
        to: str,
        template_name: str,
        language_code: str = "en",
        components: Optional[list] = None,
    ) -> dict:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
            },
        }
        if components:
            payload["template"]["components"] = components
        return await self._post(settings.messages_url, payload)

    # ── Image Message ─────────────────────────────────────────────────────────

    async def send_image(self, to: str, image_url: str, caption: str = "") -> dict:
        return await self._post(settings.messages_url, {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "image",
            "image": {"link": image_url, "caption": caption},
        })

    # ── Document Message ──────────────────────────────────────────────────────

    async def send_document(self, to: str, doc_url: str, filename: str, caption: str = "") -> dict:
        return await self._post(settings.messages_url, {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "document",
            "document": {"link": doc_url, "filename": filename, "caption": caption},
        })

    # ── Interactive List Message ───────────────────────────────────────────────

    async def send_interactive_list(
        self,
        to: str,
        header: str,
        body: str,
        footer: str,
        button_text: str,
        sections: list,
    ) -> dict:
        return await self._post(settings.messages_url, {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "header": {"type": "text", "text": header},
                "body": {"text": body},
                "footer": {"text": footer},
                "action": {"button": button_text, "sections": sections},
            },
        })

    # ── Interactive Button Message ─────────────────────────────────────────────

    async def send_interactive_buttons(
        self,
        to: str,
        body: str,
        buttons: list[dict],
        header: Optional[str] = None,
        footer: Optional[str] = None,
    ) -> dict:
        interactive = {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}}
                    for b in buttons[:3]
                ]
            },
        }
        if header:
            interactive["header"] = {"type": "text", "text": header}
        if footer:
            interactive["footer"] = {"text": footer}
        return await self._post(settings.messages_url, {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": interactive,
        })

    # ── Mark Read ─────────────────────────────────────────────────────────────

    async def mark_read(self, wa_message_id: str) -> dict:
        return await self._post(settings.messages_url, {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": wa_message_id,
        })

    # ── Reaction ──────────────────────────────────────────────────────────────

    async def send_reaction(self, to: str, wa_message_id: str, emoji: str) -> dict:
        return await self._post(settings.messages_url, {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "reaction",
            "reaction": {"message_id": wa_message_id, "emoji": emoji},
        })

    # ── Media Download ────────────────────────────────────────────────────────

    async def get_media_url(self, media_id: str) -> str:
        url = f"{settings.whatsapp_api_url}/{media_id}"
        data = await self._get(url)
        return data.get("url", "")

    async def download_media(self, media_url: str) -> bytes:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(media_url, headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"})
            r.raise_for_status()
            return r.content

    # ── Business Profile ──────────────────────────────────────────────────────

    async def get_business_profile(self) -> dict:
        url = f"{settings.whatsapp_api_url}/{settings.whatsapp_phone_number_id}/whatsapp_business_profile"
        return await self._get(url)

    async def update_business_profile(self, data: dict) -> dict:
        url = f"{settings.whatsapp_api_url}/{settings.whatsapp_phone_number_id}/whatsapp_business_profile"
        return await self._post(url, {"messaging_product": "whatsapp", **data})

    # ── Templates ─────────────────────────────────────────────────────────────

    async def list_templates(self) -> dict:
        url = f"{settings.whatsapp_api_url}/{settings.whatsapp_business_account_id}/message_templates"
        return await self._get(url)

    async def create_template(self, name: str, language: str, category: str, components: list) -> dict:
        url = f"{settings.whatsapp_api_url}/{settings.whatsapp_business_account_id}/message_templates"
        return await self._post(url, {
            "messaging_product": "whatsapp",
            "name": name,
            "language": language,
            "category": category,
            "components": components,
        })

    async def get_phone_numbers(self) -> dict:
        url = f"{settings.whatsapp_api_url}/{settings.whatsapp_business_account_id}/phone_numbers"
        return await self._get(url)


whatsapp = WhatsAppService()
