import hashlib
import hmac
import secrets
from datetime import datetime
from typing import Optional

import bcrypt
from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.admin import Admin
from app.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    # Support migration: old hashes are 64-char hex (SHA256), new are bcrypt ($2b$...)
    if hashed.startswith("$2b$") or hashed.startswith("$2a$"):
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    # Legacy SHA256 — verify then re-hash with bcrypt on next save
    return hmac.compare_digest(
        hashlib.sha256(plain.encode()).hexdigest(), hashed
    )


def is_legacy_hash(hashed: str) -> bool:
    return not (hashed.startswith("$2b$") or hashed.startswith("$2a$"))


def create_session_token() -> str:
    return secrets.token_urlsafe(32)


async def authenticate_admin(email: str, password: str, db: AsyncSession) -> Optional[Admin]:
    result = await db.execute(select(Admin).where(Admin.email == email, Admin.is_active == True))
    admin = result.scalar_one_or_none()
    if not admin or not verify_password(password, admin.password_hash):
        return None
    # Silently upgrade legacy SHA256 hash to bcrypt on successful login
    if is_legacy_hash(admin.password_hash):
        admin.password_hash = hash_password(password)
    admin.last_login = datetime.utcnow()
    return admin


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
            must_change_password=True,
        )
        db.add(admin)
        await db.commit()


def verify_webhook_signature(payload: bytes, signature: str, app_secret: str) -> bool:
    if not signature.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature[7:])
