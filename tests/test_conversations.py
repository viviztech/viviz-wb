import json
import unittest

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

import app.models  # noqa: F401 - register all tables
from app.database import Base
from app.models.audit import AuditLog
from app.models.contact import Contact
from app.models.conversation import Conversation, Message, MessageDirection, MessageType
from app.routers.conversations import delete_conversation


class DeleteConversationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()

    @staticmethod
    def request(authenticated: bool = True) -> Request:
        return Request({
            "type": "http",
            "method": "DELETE",
            "path": "/conversations/1",
            "headers": [],
            "session": {"admin_email": "admin@example.com"} if authenticated else {},
        })

    async def test_deletes_messages_and_conversation_but_keeps_contact_and_audit(self):
        async with self.sessions() as db:
            contact = Contact(phone="919999999999")
            db.add(contact)
            await db.flush()
            conversation = Conversation(contact_id=contact.id, status="open")
            db.add(conversation)
            await db.flush()
            db.add_all([
                Message(
                    conversation_id=conversation.id,
                    direction=MessageDirection.inbound,
                    message_type=MessageType.text,
                    content="Hello",
                ),
                Message(
                    conversation_id=conversation.id,
                    direction=MessageDirection.outbound,
                    message_type=MessageType.image,
                    content="[image]",
                    media_id="media-123",
                ),
            ])
            await db.commit()

            response = await delete_conversation(conversation.id, self.request(), db)
            payload = json.loads(response.body)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(payload["messages_deleted"], 2)
            self.assertEqual((await db.execute(select(func.count(Contact.id)))).scalar(), 1)
            self.assertEqual((await db.execute(select(func.count(Conversation.id)))).scalar(), 0)
            self.assertEqual((await db.execute(select(func.count(Message.id)))).scalar(), 0)
            audit = (await db.execute(select(AuditLog))).scalar_one()
            self.assertEqual(audit.action, "conversation_delete")
            self.assertEqual(audit.target_id, conversation.id)
            self.assertEqual(audit.meta["message_count"], 2)
            self.assertEqual(audit.meta["media_count"], 1)

    async def test_requires_authentication(self):
        async with self.sessions() as db:
            response = await delete_conversation(1, self.request(authenticated=False), db)
            self.assertEqual(response.status_code, 401)
