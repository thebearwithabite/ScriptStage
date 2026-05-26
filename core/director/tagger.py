"""Director tagging utilities for ScriptStage.

This module combines:
1) square-bracket audio tags (e.g. [sighs], [thoughtful]), and
2) Dramabox semantic tokens (e.g. {emotion=joy} {style=dramatic} {voice=lead_female}).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


DISALLOWED_TAGS = {"standing", "grinning", "pacing", "music"}
DEFAULT_AUDIO_TAGS = {
    "excited": ("excited",),
    "surprised": ("surprised",),
    "thoughtful": ("thoughtful",),
    "whisper": ("whisper",),
    "angry": ("angry",),
}


@dataclass(slots=True)
class DirectorOptions:
    """Controls how a line is tagged for synthesis."""

    emotion: str | None = None
    style: str | None = None
    voice: str | None = None
    tags_before: list[str] = field(default_factory=list)
    tags_after: list[str] = field(default_factory=list)


def _clean_tag(tag: str) -> str:
    return tag.strip().strip("[]{}").strip().lower()


def _filter_audio_tags(tags: Iterable[str]) -> list[str]:
    cleaned: list[str] = []
    for tag in tags:
        norm = _clean_tag(tag)
        if not norm or norm in DISALLOWED_TAGS:
            continue
        cleaned.append(norm)
    return cleaned


def _infer_default_tags(line: str) -> list[str]:
    text = line.strip()
    if not text:
        return []
    if "..." in text:
        return list(DEFAULT_AUDIO_TAGS["thoughtful"])
    if "?" in text:
        return list(DEFAULT_AUDIO_TAGS["surprised"])
    if "!" in text:
        return list(DEFAULT_AUDIO_TAGS["excited"])
    return []


def _dramabox_tokens(options: DirectorOptions) -> str:
    tokens: list[str] = []
    if options.emotion:
        tokens.append(f"{{emotion={options.emotion}}}")
    if options.style:
        tokens.append(f"{{style={options.style}}}")
    if options.voice:
        tokens.append(f"{{voice={options.voice}}}")
    return " ".join(tokens)


def enhance_dialogue_line(line: str, options: DirectorOptions | None = None) -> str:
    """Return a directed line for Dramabox while preserving original dialogue text.

    The function never rewrites the dialogue words. It only adds optional tokens/tags.
    """

    opts = options or DirectorOptions()
    before = _filter_audio_tags(opts.tags_before) or _infer_default_tags(line)
    after = _filter_audio_tags(opts.tags_after)

    prefix_parts: list[str] = []
    dramabox = _dramabox_tokens(opts)
    if dramabox:
        prefix_parts.append(dramabox)
    prefix_parts.extend(f"[{tag}]" for tag in before)

    suffix = " ".join(f"[{tag}]" for tag in after)
    base = line
    if prefix_parts:
        base = f"{' '.join(prefix_parts)} {base}"
    if suffix:
        base = f"{base} {suffix}"
    return base
