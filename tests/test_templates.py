import json
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request
from starlette.datastructures import Headers, UploadFile

import app.models  # noqa: F401 - register all tables
from app.database import Base
from app.config import settings
from app.models.template import MessageTemplate
from app.routers.templates import create_template
from app.services.media_validation import validate_template_header_upload
from app.services.template_builder import components_from_template, prepare_template
from app.services.whatsapp import WhatsAppService


class TemplateBuilderTests(unittest.TestCase):
    def test_builds_marketing_template_with_samples_and_optout_button(self):
        result = prepare_template(
            name="Viviz Brand Awareness",
            category="marketing",
            language="en",
            header_type="text",
            header_text="Grow with Viviz Technologies",
            body="Hello {{1}}, discover practical digital solutions for {{2}}.",
            footer="Viviz Technologies",
            body_examples_json=json.dumps(["Rajan", "your business"]),
            buttons_json=json.dumps([
                {"type": "URL", "text": "Learn more", "url": "https://viviz.in"},
                {"type": "QUICK_REPLY", "text": "Stop marketing"},
            ]),
        )

        self.assertEqual(result["name"], "viviz_brand_awareness")
        self.assertEqual(result["category"], "MARKETING")
        body = next(c for c in result["components"] if c["type"] == "BODY")
        self.assertEqual(body["example"]["body_text"], [["Rajan", "your business"]])
        buttons = next(c for c in result["components"] if c["type"] == "BUTTONS")
        self.assertEqual(buttons["buttons"][0]["url"], "https://viviz.in")

    def test_requires_sequential_variables_and_samples(self):
        with self.assertRaisesRegex(ValueError, "sequential"):
            prepare_template(
                name="bad_variables", category="UTILITY", language="en",
                header_type="NONE", header_text="", body="Hello {{2}}", footer="",
                body_examples_json='["Rajan"]', buttons_json="[]",
            )

        with self.assertRaisesRegex(ValueError, "sample"):
            prepare_template(
                name="missing_sample", category="UTILITY", language="en",
                header_type="NONE", header_text="", body="Hello {{1}}", footer="",
                body_examples_json="[]", buttons_json="[]",
            )

    def test_marketing_requires_optout(self):
        with self.assertRaisesRegex(ValueError, "opt-out"):
            prepare_template(
                name="promotion", category="MARKETING", language="en",
                header_type="NONE", header_text="", body="See our latest services.", footer="",
                body_examples_json="[]", buttons_json="[]",
            )

    def test_rejects_dynamic_or_insecure_urls(self):
        for url in ("http://viviz.in", "https://viviz.in/{{1}}"):
            with self.assertRaisesRegex(ValueError, "fixed HTTPS"):
                prepare_template(
                    name="bad_url", category="UTILITY", language="en",
                    header_type="NONE", header_text="", body="Your requested update.", footer="",
                    body_examples_json="[]",
                    buttons_json=json.dumps([{"type": "URL", "text": "Open", "url": url}]),
                )

    def test_authentication_uses_dedicated_meta_flow(self):
        with self.assertRaisesRegex(ValueError, "OTP"):
            prepare_template(
                name="login_code", category="AUTHENTICATION", language="en",
                header_type="NONE", header_text="", body="Code {{1}}", footer="",
                body_examples_json='["123456"]', buttons_json="[]",
            )

    def test_builds_media_header_with_meta_sample_handle(self):
        result = prepare_template(
            name="visual_update", category="UTILITY", language="en",
            header_type="IMAGE", header_text="", body="Your requested update.", footer="",
            body_examples_json="[]", buttons_json="[]", header_handle="4::sample-handle",
        )
        self.assertEqual(result["header_type"], "image")
        self.assertEqual(result["header_content"], "4::sample-handle")
        self.assertEqual(result["components"][0], {
            "type": "HEADER",
            "format": "IMAGE",
            "example": {"header_handle": ["4::sample-handle"]},
        })

        rebuilt = components_from_template(SimpleNamespace(
            header_type="image", header_content="4::sample-handle",
            body="Your requested update.", variables=[], footer=None, buttons=[],
        ))
        self.assertEqual(rebuilt[0], result["components"][0])

    def test_validates_template_media_type_and_signature(self):
        png = BytesIO(b"\x89PNG\r\n\x1a\n" + b"sample")
        filename, size, mime = validate_template_header_upload(
            png, "header.png", "image/png", "IMAGE"
        )
        self.assertEqual((filename, mime), ("header.png", "image/png"))
        self.assertGreater(size, 0)

        with self.assertRaisesRegex(ValueError, "requires an MP4"):
            validate_template_header_upload(
                BytesIO(b"\x89PNG\r\n\x1a\n" + b"sample"),
                "header.png", "image/png", "VIDEO",
            )


class CreateTemplateRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.request = Request({
            "type": "http", "method": "POST", "path": "/templates/create",
            "headers": [], "session": {"admin_email": "admin@example.com"},
        })

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_saves_local_draft_with_components(self):
        async with self.sessions() as db:
            response = await create_template(
                self.request,
                name="service_update",
                category="UTILITY",
                language="en",
                header_type="TEXT",
                header_text="Service update",
                body="Hello {{1}}, your requested update is ready.",
                footer="Viviz Technologies",
                body_examples_json='["Rajan"]',
                buttons_json='[{"type":"URL","text":"View update","url":"https://viviz.in"}]',
                submit_to_meta="false",
                db=db,
            )

            self.assertEqual(response.status_code, 200)
            template = (await db.execute(select(MessageTemplate))).scalar_one()
            self.assertEqual(template.status, "DRAFT")
            self.assertEqual(template.variables[0]["sample"], "Rajan")
            self.assertEqual(template.buttons[0]["type"], "URL")

    async def test_submits_exact_validated_components_to_meta(self):
        async with self.sessions() as db:
            with patch(
                "app.routers.templates.whatsapp.create_template",
                new=AsyncMock(return_value={"id": "meta-123", "status": "PENDING"}),
            ) as send:
                response = await create_template(
                    self.request,
                    name="brand_update",
                    category="MARKETING",
                    language="en",
                    header_type="NONE",
                    header_text="",
                    body="Discover our latest services.",
                    footer="Reply STOP MARKETING to opt out.",
                    body_examples_json="[]",
                    buttons_json="[]",
                    submit_to_meta="true",
                    db=db,
                )

            self.assertEqual(response.status_code, 200)
            components = send.await_args.kwargs["components"]
            self.assertEqual(components[0], {"type": "BODY", "text": "Discover our latest services."})
            self.assertEqual(components[1]["type"], "FOOTER")

    async def test_uploads_media_sample_and_submits_header_handle(self):
        upload = UploadFile(
            BytesIO(b"\x89PNG\r\n\x1a\n" + b"sample-image"),
            filename="launch.png",
            headers=Headers({"content-type": "image/png"}),
        )
        async with self.sessions() as db:
            with patch(
                "app.routers.templates.whatsapp.upload_template_sample",
                new=AsyncMock(return_value="4::uploaded-handle"),
            ) as media_upload, patch(
                "app.routers.templates.whatsapp.create_template",
                new=AsyncMock(return_value={"id": "meta-media-1", "status": "PENDING"}),
            ) as submit:
                response = await create_template(
                    self.request,
                    name="launch_visual",
                    category="UTILITY",
                    language="en",
                    header_type="IMAGE",
                    header_text="",
                    body="Here is your requested launch update.",
                    footer="",
                    body_examples_json="[]",
                    buttons_json="[]",
                    submit_to_meta="true",
                    header_media=upload,
                    db=db,
                )

            self.assertEqual(response.status_code, 200)
            media_upload.assert_awaited_once()
            header = submit.await_args.kwargs["components"][0]
            self.assertEqual(header["example"]["header_handle"], ["4::uploaded-handle"])
            template = (await db.execute(select(MessageTemplate))).scalar_one()
            self.assertEqual(template.header_type, "image")
            self.assertEqual(template.header_content, "4::uploaded-handle")

    async def test_media_template_cannot_save_an_expiring_handle_as_draft(self):
        async with self.sessions() as db:
            response = await create_template(
                self.request,
                name="media_draft",
                category="UTILITY",
                language="en",
                header_type="IMAGE",
                header_text="",
                body="Your requested update.",
                footer="",
                body_examples_json="[]",
                buttons_json="[]",
                submit_to_meta="false",
                header_media=None,
                db=db,
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("submitted to Meta immediately", response.body.decode())


class TemplateMediaUploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_app_resumable_upload_protocol(self):
        old_app_id = settings.meta_app_id
        settings.meta_app_id = "app-123"
        try:
            session_response = Mock()
            session_response.json.return_value = {"id": "upload:session?sig=abc"}
            session_response.raise_for_status.return_value = None
            upload_response = Mock()
            upload_response.json.return_value = {"h": "4::media-handle"}
            upload_response.raise_for_status.return_value = None
            client = AsyncMock()
            client.__aenter__.return_value = client
            client.post.side_effect = [session_response, upload_response]

            with patch("app.services.whatsapp.httpx.AsyncClient", return_value=client):
                handle = await WhatsAppService().upload_template_sample(
                    BytesIO(b"sample"), "sample.png", "image/png", 6
                )

            self.assertEqual(handle, "4::media-handle")
            first_call, second_call = client.post.await_args_list
            self.assertTrue(first_call.args[0].endswith("/app-123/uploads"))
            self.assertEqual(first_call.kwargs["params"]["file_length"], 6)
            self.assertIn("upload:session?sig=abc", second_call.args[0])
            self.assertEqual(second_call.kwargs["headers"]["file_offset"], "0")
        finally:
            settings.meta_app_id = old_app_id
