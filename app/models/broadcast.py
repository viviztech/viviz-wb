from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


class Broadcast(Base):
    __tablename__ = "broadcasts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    template_id = Column(Integer, ForeignKey("message_templates.id"), nullable=True)
    template_name = Column(String(200), nullable=True)
    template_language = Column(String(20), default="en")
    message = Column(Text, nullable=True)
    # static variables applied to all recipients e.g. {"1": "Sale 50%"}
    variables = Column(JSON, default=dict)
    # variable column mapping: {"1": "name", "2": "city"} → maps to contact fields
    variable_mapping = Column(JSON, default=dict)
    target_tags = Column(JSON, default=list)
    # target_mode: "all" | "tags" | "segment"
    target_mode = Column(String(20), default="all")
    # segment filter criteria stored as JSON
    segment_filter = Column(JSON, default=dict)
    total_count = Column(Integer, default=0)
    sent_count = Column(Integer, default=0)
    delivered_count = Column(Integer, default=0)
    read_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    retry_count = Column(Integer, default=0)
    status = Column(String(20), default="draft")  # draft, running, completed, failed, cancelled, scheduled
    scheduled_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_by = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    recipients = relationship("BroadcastRecipient", back_populates="broadcast", lazy="dynamic")


class BroadcastRecipient(Base):
    __tablename__ = "broadcast_recipients"

    id = Column(Integer, primary_key=True, index=True)
    broadcast_id = Column(Integer, ForeignKey("broadcasts.id"), nullable=False)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=False)
    wa_message_id = Column(String(100), nullable=True, index=True)
    # per-recipient resolved variables {"1": "Rajan", "2": "Chennai"}
    resolved_variables = Column(JSON, default=dict)
    status = Column(String(20), default="pending")  # pending, sent, delivered, read, failed, retry
    error_message = Column(Text, nullable=True)
    retry_attempts = Column(Integer, default=0)
    sent_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    read_at = Column(DateTime, nullable=True)

    broadcast = relationship("Broadcast", back_populates="recipients")
    contact = relationship("Contact", back_populates="broadcast_recipients")
