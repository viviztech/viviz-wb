from sqlalchemy import Column, Integer, String, Text, DateTime
from datetime import datetime
from app.database import Base


class QuickReply(Base):
    __tablename__ = "quick_replies"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(100), nullable=False)
    shortcut = Column(String(50), unique=True, nullable=True)  # e.g. /thanks
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
