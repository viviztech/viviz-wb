import json
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

import app.models  # noqa: F401 - register all tables
from app.database import Base
from app.models.template import MessageTemplate
from app.routers.templates import create_template
from app.services.template_builder import prepare_template


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
