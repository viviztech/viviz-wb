import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings, EDITABLE_SETTINGS
from app.models.setting import AppSetting

logger = logging.getLogger(__name__)


def _valid_business_phone(value: str, phone_number_id: str) -> bool:
    digits = re.sub(r"\D", "", value or "")
    id_digits = re.sub(r"\D", "", phone_number_id or "")
    return 7 <= len(digits) <= 15 and digits != id_digits


async def load_overrides(db: AsyncSession) -> None:
    """Apply DB-stored credential overrides onto the in-memory settings singleton. Called at startup."""
    result = await db.execute(select(AppSetting))
    overrides = {
        row.key: row.value
        for row in result.scalars().all()
        if row.key in EDITABLE_SETTINGS
    }
    effective_phone_id = overrides.get(
        "whatsapp_phone_number_id", settings.whatsapp_phone_number_id
    )
    for key, value in overrides.items():
        if key == "whatsapp_business_phone" and not _valid_business_phone(
            value, effective_phone_id
        ):
            logger.warning(
                "Ignoring invalid WhatsApp business phone override; use the real E.164 number, not the Phone Number ID"
            )
            continue
        setattr(settings, key, value)


async def save_override(db: AsyncSession, key: str, value: str) -> None:
    """Persist a single editable setting and apply it immediately — no restart required."""
    if key not in EDITABLE_SETTINGS:
        raise ValueError(f"{key} is not an editable setting")
    existing = await db.get(AppSetting, key)
    if existing:
        existing.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    setattr(settings, key, value)
