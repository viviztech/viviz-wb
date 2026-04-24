from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def _dispatch_scheduled_broadcasts():
    """Called every minute — finds broadcasts due to run and starts them."""
    from app.database import AsyncSessionLocal
    from app.models.broadcast import Broadcast
    from app.routers.broadcasts import _send_broadcast_messages
    import asyncio

    now = datetime.utcnow()
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Broadcast).where(
                Broadcast.status == "scheduled",
                Broadcast.scheduled_at <= now,
            )
        )
        due = result.scalars().all()
        for broadcast in due:
            broadcast.status = "running"
            broadcast.started_at = now
            await db.commit()
            asyncio.create_task(_send_broadcast_messages(broadcast.id))
            logger.info(f"Scheduled broadcast {broadcast.id} '{broadcast.name}' started")


def start_scheduler():
    scheduler.add_job(
        _dispatch_scheduled_broadcasts,
        trigger=IntervalTrigger(minutes=1),
        id="dispatch_scheduled_broadcasts",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("APScheduler started")


def stop_scheduler():
    scheduler.shutdown(wait=False)
    logger.info("APScheduler stopped")
