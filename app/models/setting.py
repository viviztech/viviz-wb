from sqlalchemy import Column, String, Text, DateTime
from datetime import datetime
from app.database import Base


class AppSetting(Base):
    """DB-stored overrides for editable config values, applied on top of .env at startup and on save."""
    __tablename__ = "app_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False, default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
