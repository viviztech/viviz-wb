import unittest
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register all tables
from app.config import settings
from app.database import Base
from app.models.mm_lite import MMLiteOnboarding
from app.models.webhook import WebhookLog
from app.services.message_handler import _handle_status_update
from app.services.mm_lite import (
    get_marketing_api_readiness,
    send_marketing_template,
    subscribe_marketing_webhook,
)


class MarketingMessagesServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.old_phone_id = settings.whatsapp_phone_number_id
        self.old_waba_id = settings.whatsapp_business_account_id
        self.old_token = settings.whatsapp_access_token
        settings.whatsapp_phone_number_id = "123456789"
        settings.whatsapp_business_account_id = "987654321"
        settings.whatsapp_access_token = "secret-test-token"

    async def asyncTearDown(self):
        settings.whatsapp_phone_number_id = self.old_phone_id
        settings.whatsapp_business_account_id = self.old_waba_id
        settings.whatsapp_access_token = self.old_token

    @staticmethod
    def _client(response_json):
        response = Mock()
        response.raise_for_status = Mock()
        response.json.return_value = response_json
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.get.return_value = response
        client.post.return_value = response
        return client

    async def test_readiness_uses_authorization_header_not_query_token(self):
        client = self._client({"id": "123456789", "quality_rating": "GREEN"})
        with patch("app.services.mm_lite.httpx.AsyncClient", return_value=client):
            result = await get_marketing_api_readiness()

        self.assertEqual(result["quality_rating"], "GREEN")
        _, kwargs = client.get.call_args
        self.assertNotIn("access_token", kwargs.get("params", {}))
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret-test-token")
        self.assertNotIn("secret-test-token", client.get.call_args.args[0])

    async def test_marketing_template_uses_dedicated_endpoint_and_official_payload(self):
        client = self._client({"messages": [{"id": "wamid.test"}]})
        components = [{"type": "body", "parameters": [{"type": "text", "text": "Asha"}]}]
        with patch("app.services.mm_lite.httpx.AsyncClient", return_value=client):
            result = await send_marketing_template(
                "919999999999", "brand_awareness", "en_US", components
            )

        self.assertEqual(result["messages"][0]["id"], "wamid.test")
        url = client.post.call_args.args[0]
        payload = client.post.call_args.kwargs["json"]
        self.assertTrue(url.endswith("/123456789/marketing_messages"))
        self.assertEqual(payload["recipient_type"], "individual")
        self.assertEqual(payload["template"]["components"], components)
        self.assertNotIn("ttl", payload)

    async def test_webhook_subscription_uses_only_messages_field(self):
        client = self._client({"success": True})
        with patch("app.services.mm_lite.httpx.AsyncClient", return_value=client):
            await subscribe_marketing_webhook("987654321")
        payload = client.post.call_args.kwargs["json"]
        self.assertEqual(payload, {"subscribed_fields": "messages"})


class MarketingMessagesWebhookTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.old_waba_id = settings.whatsapp_business_account_id
        settings.whatsapp_business_account_id = "987654321"

    async def asyncTearDown(self):
        settings.whatsapp_business_account_id = self.old_waba_id
        await self.engine.dispose()

    async def test_marketing_lite_status_webhook_records_routing_proof(self):
        status = {
            "id": "wamid.marketing",
            "status": "sent",
            "conversation": {"origin": {"type": "marketing_lite"}},
            "pricing": {"category": "marketing_lite", "pricing_model": "PMP"},
        }
        async with self.sessions() as db:
            await _handle_status_update(status, db)
            await db.commit()
            record = (
                await db.execute(select(MMLiteOnboarding))
            ).scalar_one()
            log = (
                await db.execute(select(WebhookLog))
            ).scalar_one()

        self.assertEqual(record.status, "active")
        self.assertEqual(record.tos_payload["id"], "wamid.marketing")
        self.assertEqual(log.event_type, "marketing_message_status_sent")


if __name__ == "__main__":
    unittest.main()
