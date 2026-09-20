import unittest

from app.models.template import MessageTemplate
from app.routers.broadcasts import _build_components, _is_param_mismatch_error


class BroadcastComponentTests(unittest.TestCase):
    def _template(self, **values):
        defaults = {
            "name": "test_template",
            "language": "en",
            "category": "MARKETING",
            "status": "APPROVED",
            "body": "Hello {{1}}, code {{2}}",
            "variables": [
                {"position": 1, "sample": "Asha"},
                {"position": 2, "sample": "SAVE20"},
            ],
        }
        defaults.update(values)
        return MessageTemplate(**defaults)

    def test_body_parameters_follow_numeric_template_order(self):
        template = self._template()
        components = _build_components(template, {"2": "SAVE20", "1": "Asha"})
        self.assertEqual(components, [{
            "type": "body",
            "parameters": [
                {"type": "text", "text": "Asha"},
                {"type": "text", "text": "SAVE20"},
            ],
        }])

    def test_media_header_uses_send_time_media_id(self):
        template = self._template(header_type="image")
        components = _build_components(
            template,
            {"1": "Asha", "2": "SAVE20"},
            {"__header_media_id": "media-123"},
        )
        self.assertEqual(components[0], {
            "type": "header",
            "parameters": [{"type": "image", "image": {"id": "media-123"}}],
        })

    def test_media_header_without_attachment_fails_before_send(self):
        template = self._template(header_type="video")
        with self.assertRaisesRegex(ValueError, "requires a video header attachment"):
            _build_components(template, {"1": "Asha", "2": "SAVE20"})

    def test_missing_or_empty_body_variable_is_rejected(self):
        template = self._template()
        with self.assertRaisesRegex(ValueError, "missing"):
            _build_components(template, {"1": "Asha"})
        with self.assertRaisesRegex(ValueError, "empty"):
            _build_components(template, {"1": "Asha", "2": ""})

    def test_132012_is_not_retried(self):
        self.assertTrue(_is_param_mismatch_error(
            "(#132012) Parameter format does not match format in the created template"
        ))


if __name__ == "__main__":
    unittest.main()
