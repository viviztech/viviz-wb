from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, JSON
from datetime import datetime
from app.database import Base


class MMLiteOnboarding(Base):
    __tablename__ = "mm_lite_onboarding"

    id = Column(Integer, primary_key=True, index=True)
    waba_id = Column(String(100), nullable=False, index=True)
    # Status: pending | tos_accepted | active | error
    status = Column(String(30), default="pending")
    tos_accepted_at = Column(DateTime, nullable=True)
    # Raw webhook payload stored for audit
    tos_payload = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
