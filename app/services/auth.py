import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Optional
from fastapi import Request, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.admin import Admin
from app.config import settings


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(plain: str, hashed: str) -> bool:
    return hmac.compare_digest(hash_password(plain), hashed)


def create_session_token() -> str:
    return secrets.token_urlsafe(32)


async def authenticate_admin(email: str, password: str, db: AsyncSession) -> Optional[Admin]:
    result = await db.execute(select(Admin).where(Admin.email == email, Admin.is_active == True))
    admin = result.scalar_one_or_none()
    if admin and verify_password(password, admin.password_hash):
        admin.last_login = datetime.utcnow()
        return admin
    return None


def get_session(request: Request) -> Optional[str]:
    return request.session.get("admin_email")


def require_auth(request: Request):
    if not request.session.get("admin_email"):
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return request.session.get("admin_email")


async def ensure_admin_exists(db: AsyncSession):
    result = await db.execute(select(Admin).where(Admin.email == settings.admin_email))
    if not result.scalar_one_or_none():
        admin = Admin(
            email=settings.admin_email,
            password_hash=hash_password(settings.admin_password),
            name="Viviz Admin",
        )
        db.add(admin)
        await db.commit()


def verify_webhook_signature(payload: bytes, signature: str, app_secret: str) -> bool:
    if not signature.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature[7:])
