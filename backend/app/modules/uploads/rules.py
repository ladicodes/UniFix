"""Per-purpose upload limits and visibility (API_CONTRACT §5)."""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.uploads.models import FilePurpose, FileVisibility
from app.modules.users.models import Role

JPEG, PNG, WEBP, PDF = "image/jpeg", "image/png", "image/webp", "application/pdf"
IMAGES = frozenset({JPEG, PNG, WEBP})
MB = 1024 * 1024


@dataclass(frozen=True, slots=True)
class PurposeRule:
    allowed_types: frozenset[str]
    max_bytes: int
    visibility: FileVisibility
    roles: frozenset[Role] | None = None  # None = any authenticated role


RULES: dict[FilePurpose, PurposeRule] = {
    FilePurpose.AVATAR: PurposeRule(IMAGES, 5 * MB, FileVisibility.PUBLIC),
    FilePurpose.PORTFOLIO: PurposeRule(IMAGES, 5 * MB, FileVisibility.PUBLIC, frozenset({Role.PROFESSIONAL})),
    FilePurpose.VERIFICATION_DOCUMENT: PurposeRule(
        IMAGES | {PDF}, 10 * MB, FileVisibility.PRIVATE, frozenset({Role.PROFESSIONAL})
    ),
    FilePurpose.REQUEST_MEDIA: PurposeRule(
        IMAGES, 10 * MB, FileVisibility.PRIVATE, frozenset({Role.CUSTOMER})
    ),
    FilePurpose.MESSAGE_ATTACHMENT: PurposeRule(
        IMAGES, 10 * MB, FileVisibility.PRIVATE, frozenset({Role.CUSTOMER, Role.PROFESSIONAL})
    ),
    FilePurpose.COMPLETION_EVIDENCE: PurposeRule(
        IMAGES, 10 * MB, FileVisibility.PRIVATE, frozenset({Role.PROFESSIONAL})
    ),
    FilePurpose.DISPUTE_EVIDENCE: PurposeRule(
        IMAGES, 10 * MB, FileVisibility.PRIVATE, frozenset({Role.CUSTOMER, Role.PROFESSIONAL, Role.ADMIN})
    ),
}
