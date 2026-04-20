"""Generate SRT captions from chunk results."""

from __future__ import annotations
from core.models import ChunkResult


def _ms_to_srt_time(ms: int) -> str:
    h = ms // 3_600_000
    ms %= 3_600_000
    m = ms // 60_000
    ms %= 60_000
    s = ms // 1_000
    ms %= 1_000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def generate_srt(chunks: list[ChunkResult]) -> str:
    lines: list[str] = []
    current_ms = 0
    for chunk in chunks:
        start_ms = current_ms
        end_ms = current_ms + chunk.duration_ms
        current_ms = end_ms + chunk.trailing_silence_ms
        text = chunk.text.strip()
        if not text:
            continue
        speaker = chunk.character or "NARRATOR"
        idx = len(lines) + 1
        lines.append(
            f"{idx}\n"
            f"{_ms_to_srt_time(start_ms)} --> {_ms_to_srt_time(end_ms)}\n"
            f"[{speaker}] {text}\n"
        )
    return "\n".join(lines)
