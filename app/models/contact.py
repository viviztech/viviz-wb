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
    # Legacy summary flag for marketing consent. Authorization is determined
    # from the append-only consent_events table and defaults fail-closed.
    is_opted_in = Column(Boolean, default=False)
    opt_in_source = Column(String(50), nullable=True)  # whatsapp_inbound, keyword_start, manual_admin, csv_import
    opt_in_at = Column(DateTime, nullable=True)
    opt_out_at = Column(DateTime, nullable=True)
    is_blocked = Column(Boolean, default=False)
    last_seen = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    conversations = relationship("Conversation", back_populates="contact", lazy="dynamic")
    broadcast_recipients = relationship("BroadcastRecipient", back_populates="contact", lazy="dynamic")
