import hashlib
import logging
import shutil
import uuid
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger("secondbrain.storage")


class Storage:
    """Local filesystem storage behind an S3-compatible interface.

    Content-addressed per user: data/<user_id>/<sha256[:2]>/<sha256> — the same
    file uploaded twice stores one blob; the documents table enforces the
    (user_id, sha256) uniqueness at the logical level.
    """

    def __init__(self, root: Path | None = None):
        self.root = root or get_settings().data_dir
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, user_id: uuid.UUID, sha256: str) -> Path:
        return self.root / str(user_id) / sha256[:2] / sha256

    def save(self, user_id: uuid.UUID, data: bytes) -> tuple[str, Path]:
        digest = hashlib.sha256(data).hexdigest()
        path = self._path_for(user_id, digest)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.rename(path)
        return digest, path

    def open(self, path: Path) -> bytes:
        return Path(path).read_bytes()

    def delete_user(self, user_id: uuid.UUID) -> None:
        user_dir = self.root / str(user_id)
        if user_dir.exists():
            shutil.rmtree(user_dir, ignore_errors=True)
            logger.info("deleted storage for user", extra={"user_id": str(user_id)})
