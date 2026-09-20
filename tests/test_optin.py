import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.config import settings
from app.routers import optin


class OptInPhoneTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.old_business_phone = settings.whatsapp_business_phone
        self.old_phone_id = settings.whatsapp_phone_number_id
        self.old_support_phone = settings.support_phone
        settings.whatsapp_phone_number_id = "1395769420275624"
        settings.support_phone = "+91 93440 64631"
        optin._phone_cache = ("", 0.0)

    async def asyncTearDown(self):
        settings.whatsapp_business_phone = self.old_business_phone
        settings.whatsapp_phone_number_id = self.old_phone_id
        settings.support_phone = self.old_support_phone
        optin._phone_cache = ("", 0.0)

    async def test_rejects_phone_number_id_and_resolves_meta_display_number(self):
        settings.whatsapp_business_phone = "1395769420275624"
        with patch.object(
            optin.whatsapp,
            "get_display_phone_number",
            new=AsyncMock(return_value="+91 93440 64631"),
        ) as resolver:
            phone = await optin._resolve_business_phone()
            cached = await optin._resolve_business_phone()

        self.assertEqual(phone, "+91 93440 64631")
        self.assertEqual(cached, phone)
        resolver.assert_awaited_once()
        self.assertEqual(
            optin._wa_deeplink(phone, "CONFIRM MARKETING"),
            "https://wa.me/919344064631?text=CONFIRM%20MARKETING",
        )

    async def test_uses_valid_configured_number_without_meta_call(self):
        settings.whatsapp_business_phone = "+91 93440 64631"
        with patch.object(
            optin.whatsapp,
            "get_display_phone_number",
            new=AsyncMock(),
        ) as resolver:
            phone = await optin._resolve_business_phone()
        self.assertEqual(phone, "+91 93440 64631")
        resolver.assert_not_awaited()

    async def test_uses_support_phone_when_meta_cannot_resolve_number(self):
        settings.whatsapp_business_phone = "1395769420275624"
        with patch.object(
            optin.whatsapp,
            "get_display_phone_number",
            new=AsyncMock(side_effect=RuntimeError("Meta unavailable")),
        ):
            phone = await optin._resolve_business_phone()
        self.assertEqual(phone, "+91 93440 64631")

    async def test_fails_closed_when_no_valid_phone_is_available(self):
        settings.whatsapp_business_phone = "1395769420275624"
        settings.support_phone = ""
        with patch.object(
            optin.whatsapp,
            "get_display_phone_number",
            new=AsyncMock(side_effect=RuntimeError("Meta unavailable")),
        ):
            with self.assertRaises(HTTPException) as error:
                await optin._resolve_business_phone()
        self.assertEqual(error.exception.status_code, 503)
