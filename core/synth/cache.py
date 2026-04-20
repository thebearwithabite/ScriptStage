"""Content-addressed TTS cache."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Optional


def cache_key(text: str, voice_id: str, voice_type: str, instruct: Optional[str] = None) -> str:
    """SHA256 hash of TTS parameters for cache lookup."""
    blob = f"{text}|{voice_id}|{voice_type}|{instruct or ''}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class TTSCache:
    """Filesystem-based TTS chunk cache."""

    @staticmethod
    def cache_key_for(job) -> str:
        """Compute cache key from a TTSJob."""
        return cache_key(job.text, job.voice_id, job.voice_type, job.instruct)

    def __init__(self, cache_dir: str | Path) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.wav"

    def has(self, key: str) -> bool:
        return self._path(key).exists()

    def get(self, key: str) -> Optional[Path]:
        p = self._path(key)
        return p if p.exists() else None

    def put(self, key: str, wav_path: str | Path) -> None:
        dest = self._path(key)
        shutil.copy2(str(wav_path), str(dest))
