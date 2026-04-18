from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, JSON, Enum
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.database import Base


class MessageType(str, enum.Enum):
    text = "text"
    image = "image"
    video = "video"
    audio = "audio"
    document = "document"
    template = "template"
    interactive = "interactive"
    location = "location"
    sticker = "sticker"
    reaction = "reaction"
    system = "system"


class MessageDirection(str, enum.Enum):
    inbound = "inbound"
    outbound = "outbound"


class MessageStatus(str, enum.Enum):
    sent = "sent"
    delivered = "delivered"
    read = "read"
    failed = "failed"
    pending = "pending"


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=False)
    wa_conversation_id = Column(String(100), nullable=True)
    status = Column(String(20), default="open")
    assigned_to = Column(String(100), nullable=True)
    last_message_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    contact = relationship("Contact", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", lazy="dynamic", order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    wa_message_id = Column(String(100), unique=True, nullable=True)
    direction = Column(Enum(MessageDirection), nullable=False)
    message_type = Column(Enum(MessageType), default=MessageType.text)
    content = Column(Text, nullable=True)
    media_url = Column(String(500), nullable=True)
    media_id = Column(String(200), nullable=True)
    caption = Column(Text, nullable=True)
    template_name = Column(String(200), nullable=True)
    status = Column(Enum(MessageStatus), default=MessageStatus.pending)
    error_message = Column(Text, nullable=True)
    raw_payload = Column(JSON, nullable=True)
    is_ai_reply = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="messages")
