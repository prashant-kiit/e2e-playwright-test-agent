"""One in-memory stand-in for the blob-storage seam, shared by the whole suite.

The artifact tests and the API tests each used to carry their own near-identical
fake. P2 extends the Storage protocol (`exists`, for content-addressed dedup),
and three copies of a protocol is three places to forget, so there is one here
instead -- the way delivery_helpers.py already shares the delivery doubles.

It records what was stored under which key, with the content type, so callers
can assert on uploads: `storage.objects[key] == (bytes, content_type)`.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from app.storage import content_type_for


class FakeStorage:
    """A dict with the Storage protocol bolted on."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def ensure_bucket(self) -> None:
        pass

    def put_file(self, key: str, path: Path, content_type: str | None = None) -> None:
        self.objects[key] = (path.read_bytes(), content_type or content_type_for(key))

    def get_stream(self, key: str) -> tuple[Iterator[bytes], str]:
        data, ct = self.objects[key]
        return iter([data]), ct
