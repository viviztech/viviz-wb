"""Validation helpers for media uploaded from the agent inbox."""

from dataclasses import dataclass
from pathlib import Path
import re
from typing import BinaryIO


MB = 1024 * 1024


@dataclass(frozen=True)
class MediaRule:
    message_type: str
    max_bytes: int
    extensions: frozenset[str]


MEDIA_RULES: dict[str, MediaRule] = {
    "image/jpeg": MediaRule("image", 5 * MB, frozenset({".jpg", ".jpeg"})),
    "image/png": MediaRule("image", 5 * MB, frozenset({".png"})),
    "application/pdf": MediaRule("document", 100 * MB, frozenset({".pdf"})),
    "text/plain": MediaRule("document", 100 * MB, frozenset({".txt"})),
    "application/msword": MediaRule("document", 100 * MB, frozenset({".doc"})),
    "application/vnd.ms-excel": MediaRule("document", 100 * MB, frozenset({".xls"})),
    "application/vnd.ms-powerpoint": MediaRule("document", 100 * MB, frozenset({".ppt"})),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": MediaRule(
        "document", 100 * MB, frozenset({".docx"})
    ),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": MediaRule(
        "document", 100 * MB, frozenset({".xlsx"})
    ),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": MediaRule(
        "document", 100 * MB, frozenset({".pptx"})
    ),
    "audio/aac": MediaRule("audio", 16 * MB, frozenset({".aac"})),
    "audio/amr": MediaRule("audio", 16 * MB, frozenset({".amr"})),
    "audio/mpeg": MediaRule("audio", 16 * MB, frozenset({".mp3"})),
    "audio/mp4": MediaRule("audio", 16 * MB, frozenset({".m4a", ".mp4"})),
    "audio/ogg": MediaRule("audio", 16 * MB, frozenset({".ogg", ".opus"})),
    "video/mp4": MediaRule("video", 16 * MB, frozenset({".mp4"})),
    "video/3gpp": MediaRule("video", 16 * MB, frozenset({".3gp"})),
}

MEDIA_TYPE_ALIASES = {
    "application/x-pdf": "application/pdf",
    "audio/x-aac": "audio/aac",
    "audio/x-m4a": "audio/mp4",
    "audio/mp3": "audio/mpeg",
    "audio/x-mpeg": "audio/mpeg",
    "audio/opus": "audio/ogg",
}


def safe_filename(filename: str | None) -> str:
    """Return a display-safe basename while preserving its useful extension."""
    name = Path(filename or "attachment").name
    name = re.sub(r"[^A-Za-z0-9._() -]", "_", name).strip(" .")
    return (name or "attachment")[:180]


def _signature_matches(mime_type: str, head: bytes) -> bool:
    if mime_type == "image/jpeg":
        return head.startswith(b"\xff\xd8\xff")
    if mime_type == "image/png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if mime_type == "application/pdf":
        return head.startswith(b"%PDF-")
    if mime_type == "text/plain":
        if b"\x00" in head:
            return False
        try:
            head.decode("utf-8")
            return True
        except UnicodeDecodeError:
            return False
    if mime_type in {
        "application/msword",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
    }:
        return head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    if mime_type.startswith("application/vnd.openxmlformats-officedocument"):
        return head.startswith(b"PK\x03\x04")
    if mime_type == "audio/ogg":
        return head.startswith(b"OggS")
    if mime_type == "audio/amr":
        return head.startswith(b"#!AMR")
    if mime_type == "audio/aac":
        return head.startswith(b"ADIF") or (
            len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xF6) == 0xF0
        )
    if mime_type == "audio/mpeg":
        return head.startswith(b"ID3") or (
            len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0
        )
    if mime_type in {"audio/mp4", "video/mp4", "video/3gpp"}:
        return len(head) >= 12 and head[4:8] == b"ftyp"
    return False


def validate_media_upload(
    file_obj: BinaryIO,
    filename: str | None,
    content_type: str | None,
) -> tuple[MediaRule, str, int, str]:
    """Validate declared type, extension, size and a minimal file signature."""
    mime_type = (content_type or "").split(";", 1)[0].strip().lower()
    mime_type = MEDIA_TYPE_ALIASES.get(mime_type, mime_type)
    rule = MEDIA_RULES.get(mime_type)
    if not rule:
        raise ValueError("Unsupported file type. Use JPG, PNG, PDF, Office, text, audio, MP4, or 3GP files.")

    clean_name = safe_filename(filename)
    if Path(clean_name).suffix.lower() not in rule.extensions:
        raise ValueError("The filename extension does not match the selected file type.")

    file_obj.seek(0, 2)
    size = file_obj.tell()
    file_obj.seek(0)
    if size <= 0:
        raise ValueError("The selected file is empty.")
    if size > rule.max_bytes:
        limit_mb = rule.max_bytes // MB
        raise ValueError(f"This {rule.message_type} exceeds Meta's {limit_mb} MB limit.")

    head = file_obj.read(32)
    file_obj.seek(0)
    if not _signature_matches(mime_type, head):
        raise ValueError("The file contents do not match its declared type.")

    return rule, clean_name, size, mime_type
