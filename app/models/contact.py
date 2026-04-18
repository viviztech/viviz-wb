from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String(20), unique=True, index=True, nullable=False)
    name = Column(String(200), nullable=True)
    wa_id = Column(String(20), nullable=True)
    profile_name = Column(String(200), nullable=True)
    email = Column(String(200), nullable=True)
    tags = Column(JSON, default=list)
    notes = Column(Text, nullable=True)
    is_opted_in = Column(Boolean, default=True)
    is_blocked = Column(Boolean, default=False)
    last_seen = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    conversations = relationship("Conversation", back_populates="contact", lazy="dynamic")
    broadcast_recipients = relationship("BroadcastRecipient", back_populates="contact", lazy="dynamic")
