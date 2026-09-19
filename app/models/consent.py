from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.database import Base


class ConsentEvent(Base):
    """Append-only evidence trail for category-specific WhatsApp consent."""

    __tablename__ = "consent_events"

    id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=False, index=True)
    category = Column(String(30), nullable=False, index=True)  # marketing | utility | authentication
    action = Column(String(20), nullable=False)  # granted | revoked
    business_name = Column(String(200), nullable=False)
    disclosure_text = Column(Text, nullable=False)
    source = Column(String(50), nullable=False)
    evidence = Column(Text, nullable=False)
    proof_reference = Column(String(500), nullable=True)
    privacy_policy_url = Column(String(500), nullable=True)
    actor = Column(String(200), nullable=False, default="system")
    occurred_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
