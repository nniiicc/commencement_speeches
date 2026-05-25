"""Content-addressed local blob store. Idempotent on duplicate content."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from commencement.config import CONFIG


_EXT_BY_KIND = {
    "html": "html",
    "json": "json",
    "pdf": "pdf",
    "image": "bin",
    "audio_mp3": "mp3",
    "audio_wav": "wav",
    "caption_vtt": "vtt",
}


@dataclass(frozen=True)
class BlobRef:
    content_hash: str
    storage_path: str
    bytes_len: int


class BlobStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else CONFIG.OBJECT_STORE_DIR
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, content_hash: str, kind: str) -> Path:
        ext = _EXT_BY_KIND.get(kind, "bin")
        return self.root / content_hash[:2] / content_hash[2:4] / f"{content_hash}.{ext}"

    def put(self, data: bytes, kind: str) -> BlobRef:
        content_hash = hashlib.sha256(data).hexdigest()
        path = self._path_for(content_hash, kind)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        rel = path.relative_to(self.root.parent) if path.is_absolute() else path
        return BlobRef(
            content_hash=content_hash,
            storage_path=str(rel),
            bytes_len=len(data),
        )

    def get(self, content_hash: str, kind: str) -> bytes | None:
        path = self._path_for(content_hash, kind)
        if not path.exists():
            return None
        return path.read_bytes()
