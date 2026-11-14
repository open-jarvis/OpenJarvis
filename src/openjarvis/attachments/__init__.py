"""Attachments: files and images handed to Jarvis in chat, kept for reuse."""

from openjarvis.attachments.extract import ALLOWED_EXTENSIONS, extract_text
from openjarvis.attachments.library import (
    Attachment,
    AttachmentError,
    AttachmentLibrary,
    get_attachment_library,
    make_vision_describer,
)

__all__ = [
    "ALLOWED_EXTENSIONS",
    "Attachment",
    "AttachmentError",
    "AttachmentLibrary",
    "extract_text",
    "get_attachment_library",
    "make_vision_describer",
]
