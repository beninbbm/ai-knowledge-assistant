"""Where uploaded files live. Local disk for now; the interface means S3 (or similar)
could be swapped in later without touching the rest of the app."""

from pathlib import Path
from typing import Protocol

from app.config import settings


class FileStorage(Protocol):
    def save(self, key: str, data: bytes) -> None: ...
    def path(self, key: str) -> Path: ...
    def delete(self, key: str) -> None: ...


class LocalFileStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        # Guard against keys like "../../etc/passwd" escaping the storage folder.
        if not path.is_relative_to(self.root):
            raise ValueError(f"Invalid storage key: {key!r}")
        return path

    def save(self, key: str, data: bytes) -> None:
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)


def get_storage() -> FileStorage:
    """FastAPI dependency (tests override it to use a temporary folder)."""
    return LocalFileStorage(settings.upload_path)
