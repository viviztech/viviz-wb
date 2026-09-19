import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register all tables
from app.config import settings
from app.database import Base
from app.models.contact import Contact
from app.models.template import MessageTemplate
from app.services.consent import (
    eligible_contact_ids,
    has_active_consent,
    record_consent,
    template_has_optout,
    validate_broadcast_template,
)
from app.services.message_handler import _check_optout


class ConsentComplianceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.old_privacy = settings.privacy_policy_url
        self.old_support = settings.support_email
        settings.privacy_policy_url = "https://example.com/privacy"
        settings.support_email = "support@example.com"

    async def asyncTearDown(self):
        settings.privacy_policy_url = self.old_privacy
        settings.support_email = self.old_support
        await self.engine.dispose()

    async def test_consent_is_category_specific_and_latest_event_wins(self):
        async with self.sessions() as db:
            contact = Contact(phone="919999999999", is_opted_in=False)
            db.add(contact)
            await db.flush()

            self.assertFalse(await has_active_consent(db, contact.id, "marketing"))
            await record_consent(
                db, contact, "marketing", "granted", "test",
                "Test form submission", "tester",
                disclosure_text="I agree to receive offers from Test Business on WhatsApp.",
            )
            self.assertTrue(await has_active_consent(db, contact.id, "marketing"))
            self.assertFalse(await has_active_consent(db, contact.id, "utility"))
            self.assertIn(contact.id, await eligible_contact_ids(db, "marketing"))

            await record_consent(
                db, contact, "marketing", "revoked", "test",
                "Inbound STOP", "system",
            )
            self.assertFalse(await has_active_consent(db, contact.id, "marketing"))
            self.assertNotIn(contact.id, await eligible_contact_ids(db, "marketing"))

    async def test_marketing_template_requires_optout(self):
        unsafe = MessageTemplate(
            name="promo", language="en", category="MARKETING",
            status="APPROVED", body="Save 20 percent today", is_active=True,
        )
        safe = MessageTemplate(
            name="promo_safe", language="en", category="MARKETING",
            status="APPROVED", body="Save 20 percent today",
            footer="Reply STOP MARKETING to opt out.", is_active=True,
        )
        self.assertFalse(template_has_optout(unsafe))
        self.assertTrue(template_has_optout(safe))

        async with self.sessions() as db:
            db.add_all([unsafe, safe])
            await db.commit()
            with self.assertRaisesRegex(ValueError, "opt-out"):
                await validate_broadcast_template(db, "promo", "en")
            validated = await validate_broadcast_template(db, "promo_safe", "en")
            self.assertEqual(validated.name, "promo_safe")

    async def test_unapproved_and_authentication_templates_cannot_broadcast(self):
        async with self.sessions() as db:
            db.add_all([
                MessageTemplate(
                    name="pending", language="en", category="UTILITY",
                    status="PENDING", body="Order update", is_active=True,
                ),
                MessageTemplate(
                    name="otp", language="en", category="AUTHENTICATION",
                    status="APPROVED", body="Your code is {{1}}", is_active=True,
                ),
            ])
            await db.commit()
            with self.assertRaisesRegex(ValueError, "approved"):
                await validate_broadcast_template(db, "pending", "en")
            with self.assertRaisesRegex(ValueError, "MARKETING and UTILITY"):
                await validate_broadcast_template(db, "otp", "en")

    async def test_keyword_flow_discloses_then_confirms_and_stop_revokes(self):
        async with self.sessions() as db:
            contact = Contact(phone="918888888888", is_opted_in=False)
            db.add(contact)
            await db.flush()
            with patch(
                "app.services.message_handler.whatsapp.send_text",
                new=AsyncMock(return_value={"messages": [{"id": "wamid.test"}]}),
            ):
                handled = await _check_optout(
                    "START MARKETING", contact, contact.phone, db
                )
                self.assertTrue(handled)
                self.assertFalse(await has_active_consent(db, contact.id, "marketing"))

                await _check_optout("CONFIRM MARKETING", contact, contact.phone, db)
                self.assertTrue(await has_active_consent(db, contact.id, "marketing"))
                self.assertFalse(contact.is_blocked)

                await _check_optout("STOP", contact, contact.phone, db)
                self.assertFalse(await has_active_consent(db, contact.id, "marketing"))
                self.assertTrue(contact.is_blocked)


if __name__ == "__main__":
    unittest.main()
