from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


class DripCampaign(Base):
    __tablename__ = "drip_campaigns"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    trigger_tag = Column(String(100), nullable=True)       # auto-enroll contacts with this tag
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    steps = relationship("DripStep", back_populates="campaign", order_by="DripStep.step_order", cascade="all, delete-orphan")
    enrollments = relationship("DripEnrollment", back_populates="campaign", cascade="all, delete-orphan")


class DripStep(Base):
    __tablename__ = "drip_steps"

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("drip_campaigns.id"), nullable=False)
    step_order = Column(Integer, nullable=False)           # 1, 2, 3...
    delay_days = Column(Integer, default=0)                # days after previous step
    delay_hours = Column(Integer, default=0)               # hours after previous step
    template_name = Column(String(200), nullable=True)     # approved WA template
    message = Column(Text, nullable=True)                  # or free text
    created_at = Column(DateTime, default=datetime.utcnow)

    campaign = relationship("DripCampaign", back_populates="steps")


class DripEnrollment(Base):
    __tablename__ = "drip_enrollments"

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("drip_campaigns.id"), nullable=False)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=False)
    current_step = Column(Integer, default=1)
    status = Column(String(20), default="active")          # active, completed, cancelled
    next_send_at = Column(DateTime, nullable=True)
    enrolled_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    campaign = relationship("DripCampaign", back_populates="enrollments")
