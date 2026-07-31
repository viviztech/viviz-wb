from sqlalchemy import Column, Integer, String, DateTime, JSON
from datetime import datetime
from app.database import Base


class AuditLog(Base):
    """Immutable compliance audit trail — no update/delete routes expose this table."""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    actor = Column(String(200), nullable=False)  # admin email, or "system" for automated actions
    action = Column(String(100), nullable=False)  # e.g. opt_in, opt_out, admin_login, contact_data_export, contact_data_erasure, broadcast_send
    target_type = Column(String(50), nullable=True)  # e.g. contact, broadcast, admin
    target_id = Column(Integer, nullable=True)
    meta = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
