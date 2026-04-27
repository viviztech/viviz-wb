from sqlalchemy import Column, Integer, String, DateTime, Text
from datetime import datetime
from app.database import Base


class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=True)
    business_name = Column(String(200), nullable=False)
    phone = Column(String(20), nullable=False)
    email = Column(String(200), nullable=False)
    business_type = Column(String(100), nullable=True)
    volume = Column(String(50), nullable=True)
    message = Column(Text, nullable=True)
    source = Column(String(50), default="landing_page")
    created_at = Column(DateTime, default=datetime.utcnow)
