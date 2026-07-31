from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings, EDITABLE_SETTINGS
from app.models.setting import AppSetting


async def load_overrides(db: AsyncSession) -> None:
    """Apply DB-stored credential overrides onto the in-memory settings singleton. Called at startup."""
    result = await db.execute(select(AppSetting))
    for row in result.scalars().all():
        if row.key in EDITABLE_SETTINGS:
            setattr(settings, row.key, row.value)


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
