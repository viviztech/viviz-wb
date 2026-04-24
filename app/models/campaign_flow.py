from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


class CampaignFlow(Base):
    __tablename__ = "campaign_flows"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    trigger_keyword = Column(String(100), nullable=False)   # inbound keyword that starts the flow
    match_type = Column(String(20), default="contains")     # exact | contains | starts_with
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    steps = relationship("CampaignFlowStep", back_populates="flow", order_by="CampaignFlowStep.step_order", cascade="all, delete-orphan")


class CampaignFlowStep(Base):
    __tablename__ = "campaign_flow_steps"

    id = Column(Integer, primary_key=True, index=True)
    flow_id = Column(Integer, ForeignKey("campaign_flows.id"), nullable=False)
    step_order = Column(Integer, nullable=False)
    template_name = Column(String(200), nullable=True)
    message = Column(Text, nullable=True)
    wait_for_reply = Column(Boolean, default=False)         # pause until contact replies
    reply_keyword = Column(String(100), nullable=True)      # keyword to advance to next step
    created_at = Column(DateTime, default=datetime.utcnow)

    flow = relationship("CampaignFlow", back_populates="steps")


class CampaignFlowState(Base):
    __tablename__ = "campaign_flow_states"

    id = Column(Integer, primary_key=True, index=True)
    flow_id = Column(Integer, ForeignKey("campaign_flows.id"), nullable=False)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=False)
    current_step = Column(Integer, default=1)
    status = Column(String(20), default="active")           # active | completed | abandoned
    started_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
