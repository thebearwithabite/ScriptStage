"""Generate JSON captions from chunk results."""

from __future__ import annotations
from core.models import ChunkResult


def generate_json_captions(chunks: list[ChunkResult]) -> dict:
    entries: list[dict] = []
    current_ms = 0
    for chunk in chunks:
        start_ms = current_ms
        end_ms = current_ms + chunk.duration_ms
        current_ms = end_ms + chunk.trailing_silence_ms
        if not chunk.text.strip():
            continue
        entries.append({
            "id": chunk.job_id,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "text": chunk.text,
            "speaker": chunk.character or "NARRATOR",
            "element_ids": chunk.element_ids,
            "scene": chunk.scene,
            "type": chunk.element_type,
        })
    return {"captions": entries}
