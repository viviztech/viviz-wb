import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

import app.models  # noqa: F401 - register all tables
from app.config import settings
from app.database import Base
from app.models.setting import AppSetting
from app.routers.settings import _valid_display_phone, test_connection


class PhoneSettingValidationTests(unittest.TestCase):
    def test_accepts_e164_display_number_and_rejects_phone_number_id(self):
        phone_id = "1395769420275624"
        self.assertTrue(_valid_display_phone("+91 93440 64631", phone_id))
        self.assertFalse(_valid_display_phone(phone_id, phone_id))
        self.assertFalse(_valid_display_phone("123", phone_id))


class TestConnectionSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.old_phone = settings.whatsapp_business_phone
        self.old_phone_id = settings.whatsapp_phone_number_id
        self.old_token = settings.whatsapp_access_token
        settings.whatsapp_phone_number_id = "1395769420275624"
        settings.whatsapp_access_token = "test-token"

    async def asyncTearDown(self):
        settings.whatsapp_business_phone = self.old_phone
        settings.whatsapp_phone_number_id = self.old_phone_id
        settings.whatsapp_access_token = self.old_token
        await self.engine.dispose()

    async def test_successful_meta_check_persists_display_number(self):
        request = Request({
            "type": "http",
            "method": "POST",
            "path": "/settings/test-connection",
            "headers": [],
            "session": {"admin_email": "admin@example.com"},
        })
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "verified_name": "Viviz Technologies",
            "display_phone_number": "+91 93440 64631",
            "quality_rating": "GREEN",
        }
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.get.return_value = response

        async with self.sessions() as db:
            with patch("app.routers.settings.httpx.AsyncClient", return_value=client):
                result = await test_connection(request, db)
            await db.flush()
            stored = await db.get(AppSetting, "whatsapp_business_phone")

        payload = json.loads(result.body)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["phone_saved"])
        self.assertEqual(settings.whatsapp_business_phone, "+91 93440 64631")
        self.assertEqual(stored.value, "+91 93440 64631")
