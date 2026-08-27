"""Media limits and object keys.

The API never proxies bytes. A phone uploads straight to object storage with a presigned
PUT, which keeps a 5MB photo from occupying a request worker on a service that is also
trying to accept SOS messages.

**Limits are enforced at presign, not after upload.** The brief is explicit and the reason
is the citizen's data allowance: someone on a failing network who has just spent four
minutes uploading a photo should not then be told it was too large. Refusing before the
first byte moves costs nothing and wastes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from sarana_shared.domain.ids import uuid7
from sarana_shared.domain.time import utc_now

MAX_AUDIO_SECONDS: Final = 30
MAX_AUDIO_BYTES: Final = 2 * 1024 * 1024
MAX_PHOTO_BYTES: Final = 5 * 1024 * 1024
MAX_PHOTOS_PER_REPORT: Final = 3

PRESIGN_TTL_SECONDS: Final = 900

ALLOWED_IMAGE_TYPES: Final[frozenset[str]] = frozenset(
    {"image/jpeg", "image/png", "image/webp"}
)
ALLOWED_AUDIO_TYPES: Final[frozenset[str]] = frozenset(
    {"audio/mpeg", "audio/mp4", "audio/aac", "audio/ogg", "audio/wav", "audio/webm"}
)


class MediaRefused(ValueError):
    """The upload was refused before it started."""


@dataclass(frozen=True, slots=True)
class UploadRequest:
    """What a client says it is about to upload."""

    content_type: str
    size_bytes: int
    duration_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class UploadGrant:
    """Where the client may put one object."""

    key: str
    content_type: str
    max_bytes: int
    expires_in: int = PRESIGN_TTL_SECONDS


def object_key(report_id: UUID, *, at: datetime | None = None) -> str:
    """`{yyyy}/{mm}/{dd}/{report_id}/{uuid7}` - never a user-supplied name.

    Date-partitioned so a lifecycle rule can move a whole day to cold storage, and
    server-generated so a filename can never traverse a path or collide with another
    report's object.
    """
    moment = at or utc_now()
    return f"{moment:%Y/%m/%d}/{report_id}/{uuid7()}"


def check_photo(request: UploadRequest, *, already_attached: int = 0) -> None:
    """Refuse a photo that cannot be accepted.

    Raises:
        MediaRefused: mapped to 422, before any bytes are sent.
    """
    if request.content_type not in ALLOWED_IMAGE_TYPES:
        raise MediaRefused(
            f"{request.content_type!r} is not an accepted image type; "
            f"expected one of {', '.join(sorted(ALLOWED_IMAGE_TYPES))}"
        )
    if request.size_bytes > MAX_PHOTO_BYTES:
        raise MediaRefused(
            f"a photo may be at most {MAX_PHOTO_BYTES // (1024 * 1024)}MB; "
            f"this one is {request.size_bytes / (1024 * 1024):.1f}MB. "
            "Refused before upload so the data is not spent."
        )
    if already_attached >= MAX_PHOTOS_PER_REPORT:
        raise MediaRefused(
            f"a report carries at most {MAX_PHOTOS_PER_REPORT} photos; "
            f"this one already has {already_attached}"
        )


def check_audio(request: UploadRequest) -> None:
    """Refuse an audio clip that cannot be accepted."""
    if request.content_type not in ALLOWED_AUDIO_TYPES:
        raise MediaRefused(
            f"{request.content_type!r} is not an accepted audio type; "
            f"expected one of {', '.join(sorted(ALLOWED_AUDIO_TYPES))}"
        )
    if request.size_bytes > MAX_AUDIO_BYTES:
        raise MediaRefused(
            f"an audio clip may be at most {MAX_AUDIO_BYTES // (1024 * 1024)}MB; "
            f"this one is {request.size_bytes / (1024 * 1024):.1f}MB"
        )
    if request.duration_seconds is not None and request.duration_seconds > MAX_AUDIO_SECONDS:
        raise MediaRefused(
            f"an audio clip may be at most {MAX_AUDIO_SECONDS}s; "
            f"this one is {request.duration_seconds:.0f}s"
        )


def grant_for_photo(
    report_id: UUID, request: UploadRequest, *, already_attached: int = 0
) -> UploadGrant:
    """Check a photo and produce its key."""
    check_photo(request, already_attached=already_attached)
    return UploadGrant(
        key=object_key(report_id),
        content_type=request.content_type,
        max_bytes=MAX_PHOTO_BYTES,
    )


def grant_for_audio(report_id: UUID, request: UploadRequest) -> UploadGrant:
    """Check an audio clip and produce its key."""
    check_audio(request)
    return UploadGrant(
        key=object_key(report_id),
        content_type=request.content_type,
        max_bytes=MAX_AUDIO_BYTES,
    )
