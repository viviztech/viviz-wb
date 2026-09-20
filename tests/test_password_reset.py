import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

import app.models  # noqa: F401 - register all tables
from app.config import settings
from app.database import Base
from app.models.admin import Admin
from app.models.audit import AuditLog
from app.models.password_reset import PasswordResetToken
from app.routers.auth import forgot_password, reset_password
from app.services.auth import hash_password, verify_password
from app.services.password_reset import create_reset_token, get_valid_reset


class PasswordResetTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.old_ttl = settings.password_reset_ttl_minutes
        settings.password_reset_ttl_minutes = 30

    async def asyncTearDown(self):
        settings.password_reset_ttl_minutes = self.old_ttl
        await self.engine.dispose()

    async def _admin(self, db):
        admin = Admin(
            email="admin@example.com",
            password_hash=hash_password("OldPassword1"),
            name="Admin",
            is_active=True,
        )
        db.add(admin)
        await db.flush()
        return admin

    async def test_token_is_stored_hashed_and_previous_token_is_invalidated(self):
        async with self.sessions() as db:
            admin = await self._admin(db)
            first = await create_reset_token(db, admin, "127.0.0.1")
            second = await create_reset_token(db, admin, "127.0.0.1")
            await db.commit()

            rows = (await db.execute(select(PasswordResetToken))).scalars().all()
            self.assertEqual(len(rows), 2)
            self.assertFalse(any(row.token_hash in {first, second} for row in rows))
            self.assertIsNone(await get_valid_reset(db, first))
            self.assertIsNotNone(await get_valid_reset(db, second))

    async def test_expired_token_is_rejected(self):
        async with self.sessions() as db:
            admin = await self._admin(db)
            token = await create_reset_token(db, admin)
            reset = (await db.execute(select(PasswordResetToken))).scalar_one()
            reset.expires_at = datetime.utcnow() - timedelta(seconds=1)
            await db.commit()
            self.assertIsNone(await get_valid_reset(db, token))

    async def test_reset_changes_password_and_consumes_token(self):
        request = Request({
            "type": "http",
            "method": "POST",
            "path": "/reset-password",
            "headers": [],
            "session": {"admin_email": "stale@example.com"},
            "client": ("127.0.0.1", 1234),
        })
        async with self.sessions() as db:
            admin = await self._admin(db)
            admin_id = admin.id
            token = await create_reset_token(db, admin)
            await db.commit()

            response = await reset_password.__wrapped__(
                request=request,
                token=token,
                new_password="NewPassword2",
                confirm_password="NewPassword2",
                db=db,
            )

            refreshed = await db.get(Admin, admin_id)
            audit = (
                await db.execute(
                    select(AuditLog).where(AuditLog.action == "password_reset_completed")
                )
            ).scalar_one()
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers["location"], "/login?reset=success")
            self.assertTrue(verify_password("NewPassword2", refreshed.password_hash))
            self.assertIsNone(await get_valid_reset(db, token))
            self.assertEqual(audit.target_id, admin_id)
            self.assertNotIn("admin_email", request.session)

    async def test_weak_password_does_not_consume_token(self):
        request = Request({
            "type": "http", "method": "POST", "path": "/reset-password",
            "headers": [], "session": {}, "client": ("127.0.0.1", 1234),
        })
        async with self.sessions() as db:
            admin = await self._admin(db)
            token = await create_reset_token(db, admin)
            await db.commit()
            response = await reset_password.__wrapped__(
                request=request,
                token=token,
                new_password="weak",
                confirm_password="weak",
                db=db,
            )
            self.assertEqual(response.status_code, 400)
            self.assertIsNotNone(await get_valid_reset(db, token))

    async def test_forgot_password_response_does_not_reveal_account(self):
        def request():
            return Request({
                "type": "http", "method": "POST", "path": "/forgot-password",
                "headers": [], "session": {}, "client": ("127.0.0.1", 1234),
            })

        async with self.sessions() as db:
            await self._admin(db)
            await db.commit()
            with patch(
                "app.routers.auth.send_password_reset_email", new=AsyncMock()
            ) as send:
                known = await forgot_password.__wrapped__(
                    request=request(), email="admin@example.com", db=db
                )
                unknown = await forgot_password.__wrapped__(
                    request=request(), email="nobody@example.com", db=db
                )

        generic = b"If an active account matches that email"
        self.assertIn(generic, known.body)
        self.assertIn(generic, unknown.body)
        self.assertEqual(send.await_count, 1)
        self.assertEqual(known.headers["cache-control"], "no-store")


if __name__ == "__main__":
    unittest.main()
