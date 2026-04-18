from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, Boolean
from datetime import datetime
from app.database import Base


class MessageTemplate(Base):
    __tablename__ = "message_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), unique=True, nullable=False)
    language = Column(String(10), default="en")
    category = Column(String(50), nullable=False)  # MARKETING, UTILITY, AUTHENTICATION
    status = Column(String(30), default="PENDING")  # APPROVED, PENDING, REJECTED
    wa_template_id = Column(String(100), nullable=True)
    header_type = Column(String(20), nullable=True)  # text, image, video, document
    header_content = Column(Text, nullable=True)
    body = Column(Text, nullable=False)
    footer = Column(Text, nullable=True)
    buttons = Column(JSON, default=list)
    variables = Column(JSON, default=list)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
