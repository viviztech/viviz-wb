from sqlalchemy.ext.asyncio import AsyncSession
from app.models.audit import AuditLog


async def log_event(
    db: AsyncSession,
    actor: str,
    action: str,
    target_type: str | None = None,
    target_id: int | None = None,
    meta: dict | None = None,
) -> None:
    """Append an entry to the compliance audit trail. Never raises — auditing must not break the caller's flow."""
    try:
        db.add(AuditLog(
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            meta=meta or {},
        ))
        await db.flush()
    except Exception:
        pass
