import io
import json
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.datastructures import Headers
from starlette.requests import Request

import app.models  # noqa: F401 - register all tables
from app.database import Base
from app.models.contact import Contact
from app.models.conversation import Conversation, Message, MessageType
from app.routers.conversations import send_media_message
from app.services.media_validation import MB, validate_media_upload
from app.services.whatsapp import WhatsAppService


class MediaValidationTests(unittest.TestCase):
    def test_valid_jpeg(self):
        file_obj = io.BytesIO(b"\xff\xd8\xff\xe0" + b"test-image")
        rule, name, size, mime_type = validate_media_upload(file_obj, "photo.jpg", "image/jpeg")
        self.assertEqual(rule.message_type, "image")
        self.assertEqual(name, "photo.jpg")
        self.assertEqual(size, 14)
        self.assertEqual(mime_type, "image/jpeg")
        self.assertEqual(file_obj.tell(), 0)

    def test_normalizes_browser_m4a_type(self):
        file_obj = io.BytesIO(b"\x00\x00\x00\x18ftypM4A " + b"audio")
        rule, _, _, mime_type = validate_media_upload(file_obj, "voice.m4a", "audio/x-m4a")
        self.assertEqual(rule.message_type, "audio")
        self.assertEqual(mime_type, "audio/mp4")

    def test_rejects_mismatched_signature(self):
        with self.assertRaisesRegex(ValueError, "contents"):
            validate_media_upload(io.BytesIO(b"not-a-pdf"), "invoice.pdf", "application/pdf")

    def test_rejects_wrong_extension(self):
        with self.assertRaisesRegex(ValueError, "extension"):
            validate_media_upload(io.BytesIO(b"%PDF-1.7"), "invoice.exe", "application/pdf")

    def test_rejects_oversized_image(self):
        file_obj = io.BytesIO(b"\xff\xd8\xff" + b"x" * (5 * MB))
        with self.assertRaisesRegex(ValueError, "5 MB"):
            validate_media_upload(file_obj, "large.jpg", "image/jpeg")


class WhatsAppMediaPayloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_document_by_media_id(self):
        service = WhatsAppService()
        service._post = AsyncMock(return_value={"messages": [{"id": "wamid.test"}]})

        await service.send_media(
            "919999999999", "document", "media-123",
            caption="Your invoice", filename="invoice.pdf",
        )

        payload = service._post.await_args.args[1]
        self.assertEqual(payload["type"], "document")
        self.assertEqual(payload["document"]["id"], "media-123")
        self.assertEqual(payload["document"]["filename"], "invoice.pdf")
        self.assertEqual(payload["document"]["caption"], "Your invoice")

    async def test_audio_does_not_include_unsupported_caption(self):
        service = WhatsAppService()
        service._post = AsyncMock(return_value={"messages": [{"id": "wamid.test"}]})

        await service.send_media("919999999999", "audio", "media-456", caption="Ignored")

        payload = service._post.await_args.args[1]
        self.assertEqual(payload["audio"], {"id": "media-456"})


class ConversationMediaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_uploads_sends_and_persists_media(self):
        async with self.sessions() as db:
            contact = Contact(phone="919999999999", is_blocked=False)
            db.add(contact)
            await db.flush()
            conversation = Conversation(contact_id=contact.id, last_inbound_at=datetime.utcnow())
            db.add(conversation)
            await db.flush()

            request = Request({
                "type": "http",
                "method": "POST",
                "path": f"/conversations/{conversation.id}/send-media",
                "headers": [],
                "session": {"admin_email": "admin@example.com"},
            })
            upload = UploadFile(
                io.BytesIO(b"\xff\xd8\xff\xe0test-image"),
                filename="project-photo.jpg",
                headers=Headers({"content-type": "image/jpeg"}),
            )

            with (
                patch(
                    "app.routers.conversations.whatsapp.upload_media",
                    new=AsyncMock(return_value={"id": "media-123"}),
                ),
                patch(
                    "app.routers.conversations.whatsapp.send_media",
                    new=AsyncMock(return_value={"messages": [{"id": "wamid.123"}]}),
                ),
            ):
                response = await send_media_message(
                    conversation.id, request, upload, "Project preview", db
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(json.loads(response.body)["message_type"], "image")
            message = (await db.execute(select(Message))).scalar_one()
            self.assertEqual(message.message_type, MessageType.image)
            self.assertEqual(message.media_id, "media-123")
            self.assertEqual(message.caption, "Project preview")
            self.assertEqual(message.raw_payload["filename"], "project-photo.jpg")


if __name__ == "__main__":
    unittest.main()
