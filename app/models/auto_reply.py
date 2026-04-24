from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime
from datetime import datetime
from app.database import Base


class AutoReply(Base):
    __tablename__ = "auto_replies"

    id = Column(Integer, primary_key=True, index=True)
    keyword = Column(String(100), nullable=False)          # trigger keyword (case-insensitive)
    match_type = Column(String(20), default="contains")    # exact | contains | starts_with
    template_name = Column(String(200), nullable=True)     # send approved WA template
    reply_text = Column(Text, nullable=True)               # or free-text reply
    is_active = Column(Boolean, default=True)
    priority = Column(Integer, default=0)                  # higher = checked first
    trigger_count = Column(Integer, default=0)             # how many times fired
    created_at = Column(DateTime, default=datetime.utcnow)
