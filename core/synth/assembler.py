"""Assemble synthesized chunks into a full table-read audio file."""

from __future__ import annotations
import wave
from pathlib import Path

from core.models import ChunkResult

SAMPLE_RATE = 24000

GAP_SCENE_CHANGE = 1.5
GAP_DIFFERENT_CHARACTER = 0.5
GAP_ACTION_TO_DIALOGUE = 0.3
GAP_SAME_CHARACTER = 0.2


def _silence_frames(duration_s: float) -> bytes:
    return b"\x00\x00" * int(SAMPLE_RATE * duration_s)


def _compute_gap(prev: ChunkResult, curr: ChunkResult) -> float:
    if prev.scene and curr.scene and prev.scene != curr.scene:
        return GAP_SCENE_CHANGE
    narration_types = {"action", "slug", "transition"}
    prev_narr = prev.element_type in narration_types
    curr_narr = curr.element_type in narration_types
    prev_dial = prev.element_type == "dialogue"
    curr_dial = curr.element_type == "dialogue"
    if (prev_narr and curr_dial) or (prev_dial and curr_narr):
        return GAP_ACTION_TO_DIALOGUE
    if prev_dial and curr_dial:
        if prev.character and curr.character and prev.character == curr.character:
            return GAP_SAME_CHARACTER
        return GAP_DIFFERENT_CHARACTER
    return GAP_ACTION_TO_DIALOGUE


def assemble_audio(chunks: list[ChunkResult], output_dir: Path) -> Path:
    output_dir = Path(output_dir)
    chunks_dir = output_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    full_path = output_dir / "table_read_full.wav"
    full_wav = wave.open(str(full_path), "wb")
    full_wav.setnchannels(1)
    full_wav.setsampwidth(2)
    full_wav.setframerate(SAMPLE_RATE)

    for i, chunk in enumerate(chunks):
        src = Path(chunk.wav_path)
        dst = chunks_dir / f"{i + 1:04d}.wav"
        if src.exists():
            dst.write_bytes(src.read_bytes())

        if i > 0:
            gap = _compute_gap(chunks[i - 1], chunk)
            chunks[i - 1].trailing_silence_ms = int(gap * 1000)
            full_wav.writeframes(_silence_frames(gap))

        if src.exists():
            with wave.open(str(src), "rb") as wf:
                full_wav.writeframes(wf.readframes(wf.getnframes()))

    full_wav.close()
    return full_path
