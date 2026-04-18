from sqlalchemy import Column, Integer, String, DateTime, JSON, Text
from datetime import datetime
from app.database import Base


class WebhookLog(Base):
    __tablename__ = "webhook_logs"

    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String(100), nullable=True)
    wa_message_id = Column(String(100), nullable=True)
    from_phone = Column(String(20), nullable=True)
    payload = Column(JSON, nullable=True)
    processed = Column(String(10), default="yes")
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
