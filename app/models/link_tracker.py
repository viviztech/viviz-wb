from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from datetime import datetime
from app.database import Base


class TrackedLink(Base):
    __tablename__ = "tracked_links"

    id = Column(Integer, primary_key=True, index=True)
    short_code = Column(String(20), unique=True, nullable=False, index=True)
    original_url = Column(String(2000), nullable=False)
    campaign_name = Column(String(200), nullable=True)      # for grouping
    click_count = Column(Integer, default=0)
    unique_clicks = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class LinkClick(Base):
    __tablename__ = "link_clicks"

    id = Column(Integer, primary_key=True, index=True)
    link_id = Column(Integer, ForeignKey("tracked_links.id"), nullable=False)
    contact_phone = Column(String(20), nullable=True)       # if identifiable
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    clicked_at = Column(DateTime, default=datetime.utcnow)
