"""Secure administrator password-reset token and email handling."""

import asyncio
import hashlib
import logging
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.admin import Admin
from app.models.password_reset import PasswordResetToken

logger = logging.getLogger(__name__)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_reset_token(
    db: AsyncSession, admin: Admin, requested_ip: str | None = None
) -> str:
    """Create a single-use token and invalidate previous unused tokens."""
    now = datetime.utcnow()
    await db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.admin_id == admin.id,
            PasswordResetToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    token = secrets.token_urlsafe(32)
    db.add(PasswordResetToken(
        admin_id=admin.id,
        token_hash=_token_hash(token),
        expires_at=now + timedelta(minutes=settings.password_reset_ttl_minutes),
        requested_ip=(requested_ip or "")[:64] or None,
    ))
    await db.flush()
    return token


async def get_valid_reset(
    db: AsyncSession, token: str, lock: bool = False
) -> tuple[PasswordResetToken, Admin] | None:
    if not token or len(token) > 200:
        return None
    query = select(PasswordResetToken).where(
        PasswordResetToken.token_hash == _token_hash(token),
        PasswordResetToken.used_at.is_(None),
        PasswordResetToken.expires_at > datetime.utcnow(),
    )
    if lock:
        query = query.with_for_update()
    reset = (await db.execute(query)).scalar_one_or_none()
    if not reset:
        return None
    admin = await db.get(Admin, reset.admin_id)
    if not admin or not admin.is_active:
        return None
    return reset, admin


def email_is_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_from_email)


def _send_email(message: EmailMessage) -> None:
    with smtplib.SMTP(settings.smtp_host, int(settings.smtp_port), timeout=15) as smtp:
        smtp.ehlo()
        if settings.smtp_use_tls:
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)


async def send_password_reset_email(admin: Admin, token: str) -> None:
    """Send the raw token only to the administrator's registered email."""
    if not email_is_configured():
        raise RuntimeError("SMTP password-reset email is not configured")
    reset_url = f"{settings.app_url.rstrip('/')}/reset-password?token={token}"
    minutes = settings.password_reset_ttl_minutes
    message = EmailMessage()
    message["Subject"] = f"Reset your {settings.app_name} password"
    message["From"] = settings.smtp_from_email
    message["To"] = admin.email
    message.set_content(
        f"Hello {admin.name or 'Administrator'},\n\n"
        f"A password reset was requested for your {settings.app_name} account.\n\n"
        f"Open this link to choose a new password:\n{reset_url}\n\n"
        f"This link expires in {minutes} minutes and can be used once. "
        "If you did not request this, ignore this email.\n"
    )
    await asyncio.to_thread(_send_email, message)
