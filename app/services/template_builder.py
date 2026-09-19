"""Validation and Meta component construction for message templates."""

import json
import re
from urllib.parse import urlparse


TEMPLATE_NAME_RE = re.compile(r"^[a-z0-9_]{1,512}$")
VARIABLE_RE = re.compile(r"\{\{(\d+)\}\}")


def extract_variable_numbers(text: str) -> list[int]:
    return sorted({int(value) for value in VARIABLE_RE.findall(text or "")})


def _validate_variables(body: str, examples: list[str]) -> list[dict]:
    numbers = extract_variable_numbers(body)
    if numbers and numbers != list(range(1, len(numbers) + 1)):
        raise ValueError("Body variables must be sequential: {{1}}, {{2}}, {{3}}.")
    if len(examples) != len(numbers) or any(not str(value).strip() for value in examples):
        raise ValueError("Provide one non-empty sample value for every body variable.")
    return [
        {"position": number, "sample": str(examples[index]).strip()}
        for index, number in enumerate(numbers)
    ]


def _validate_buttons(raw_buttons: list[dict]) -> list[dict]:
    if len(raw_buttons) > 3:
        raise ValueError("Add no more than three buttons to a template.")

    buttons: list[dict] = []
    for raw in raw_buttons:
        button_type = str(raw.get("type") or "").upper()
        text = str(raw.get("text") or "").strip()
        if button_type not in {"QUICK_REPLY", "URL", "PHONE_NUMBER"}:
            raise ValueError("Choose a supported button type.")
        if not 1 <= len(text) <= 25:
            raise ValueError("Button labels must contain 1 to 25 characters.")

        button = {"type": button_type, "text": text}
        if button_type == "URL":
            url = str(raw.get("url") or "").strip()
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.netloc or "{{" in url:
                raise ValueError("Website buttons require a fixed HTTPS URL.")
            button["url"] = url
        elif button_type == "PHONE_NUMBER":
            phone = re.sub(r"[\s()-]", "", str(raw.get("phone_number") or ""))
            if not re.fullmatch(r"\+?[1-9]\d{6,14}", phone):
                raise ValueError("Enter a valid international phone number for the call button.")
            button["phone_number"] = phone
        buttons.append(button)
    return buttons


def prepare_template(
    *,
    name: str,
    category: str,
    language: str,
    header_type: str,
    header_text: str,
    body: str,
    footer: str,
    body_examples_json: str,
    buttons_json: str,
    header_handle: str = "",
) -> dict:
    clean_name = name.strip().lower().replace(" ", "_")
    if not TEMPLATE_NAME_RE.fullmatch(clean_name):
        raise ValueError("Template name can contain only lowercase letters, numbers, and underscores.")

    category = category.strip().upper()
    if category not in {"MARKETING", "UTILITY"}:
        raise ValueError("Create authentication templates through Meta's dedicated OTP template flow.")

    language = language.strip()
    if not re.fullmatch(r"[a-z]{2,3}(?:_[A-Z]{2})?", language):
        raise ValueError("Choose a valid template language.")

    header_type = header_type.strip().upper() or "NONE"
    header_text = header_text.strip()
    if header_type not in {"NONE", "TEXT", "IMAGE", "VIDEO", "DOCUMENT"}:
        raise ValueError("Choose no header, text, image, video, or document.")
    if header_type == "TEXT":
        if not header_text or len(header_text) > 60 or "\n" in header_text:
            raise ValueError("Text headers must contain 1 to 60 characters on one line.")
        if VARIABLE_RE.search(header_text):
            raise ValueError("Header variables are not supported by this broadcast workflow.")
    elif header_type == "NONE":
        header_text = ""
    else:
        header_text = ""
        if not header_handle.strip():
            raise ValueError("Upload a sample file for the media header.")

    body = body.strip()
    footer = footer.strip()
    if not body or len(body) > 1024:
        raise ValueError("Template body must contain 1 to 1,024 characters.")
    if len(footer) > 60:
        raise ValueError("Template footer can contain up to 60 characters.")

    try:
        examples = json.loads(body_examples_json or "[]")
        raw_buttons = json.loads(buttons_json or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError("Template examples or buttons are malformed.") from exc
    if not isinstance(examples, list) or not isinstance(raw_buttons, list):
        raise ValueError("Template examples and buttons must be lists.")

    variables = _validate_variables(body, examples)
    buttons = _validate_buttons(raw_buttons)

    if category == "MARKETING":
        optout_text = " ".join(
            [body, footer, *[str(button.get("text") or "") for button in buttons]]
        ).lower()
        if not any(term in optout_text for term in ("stop", "unsubscribe", "opt out", "opt-out")):
            raise ValueError("Marketing templates need STOP/opt-out wording or an opt-out quick-reply button.")

    components: list[dict] = []
    if header_type == "TEXT":
        components.append({"type": "HEADER", "format": "TEXT", "text": header_text})
    elif header_type in {"IMAGE", "VIDEO", "DOCUMENT"}:
        components.append({
            "type": "HEADER",
            "format": header_type,
            "example": {"header_handle": [header_handle.strip()]},
        })

    body_component: dict = {"type": "BODY", "text": body}
    if variables:
        body_component["example"] = {
            "body_text": [[item["sample"] for item in variables]]
        }
    components.append(body_component)
    if footer:
        components.append({"type": "FOOTER", "text": footer})
    if buttons:
        components.append({"type": "BUTTONS", "buttons": buttons})

    return {
        "name": clean_name,
        "category": category,
        "language": language,
        "header_type": header_type.lower() if header_type != "NONE" else None,
        "header_content": (header_text or header_handle.strip()) or None,
        "body": body,
        "footer": footer or None,
        "variables": variables,
        "buttons": buttons,
        "components": components,
    }


def components_from_template(template) -> list[dict]:
    components: list[dict] = []
    if template.header_type == "text" and template.header_content:
        components.append({"type": "HEADER", "format": "TEXT", "text": template.header_content})
    elif template.header_type in {"image", "video", "document"} and template.header_content:
        components.append({
            "type": "HEADER",
            "format": template.header_type.upper(),
            "example": {"header_handle": [template.header_content]},
        })
    body_component: dict = {"type": "BODY", "text": template.body}
    variables = template.variables or []
    if variables:
        body_component["example"] = {
            "body_text": [[
                str(item.get("sample") or "") if isinstance(item, dict) else str(item)
                for item in variables
            ]]
        }
    components.append(body_component)
    if template.footer:
        components.append({"type": "FOOTER", "text": template.footer})
    if template.buttons:
        components.append({"type": "BUTTONS", "buttons": template.buttons})
    return components
