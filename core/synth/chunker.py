"""Convert parsed script + casting into ordered TTS jobs."""

from __future__ import annotations
import re
from typing import Optional

from core.models import CastingResult, Script, ScriptElement, TTSJob

MAX_CHARS_PER_JOB = 500

PARENTHETICAL_TO_INSTRUCT: dict[str, Optional[str]] = {
    "whispers": "Speak in a quiet whisper",
    "whispering": "Speak in a quiet whisper",
    "shouting": "Speak loudly and forcefully",
    "shouts": "Speak loudly and forcefully",
    "yelling": "Speak loudly and forcefully",
    "screaming": "Speak loudly and with intensity",
    "sotto": "Speak quietly, under the breath",
    "sotto voce": "Speak quietly, under the breath",
    "angry": "Speak with anger and frustration",
    "angrily": "Speak with anger and frustration",
    "excited": "Speak with excitement and energy",
    "sarcastic": "Speak with dry sarcasm",
    "sarcastically": "Speak with dry sarcasm",
    "laughing": "Speak while laughing lightly",
    "crying": "Speak while crying, voice breaking",
    "quietly": "Speak softly and gently",
    "loud": "Speak loudly",
    "beat": None,
    "a beat": None,
    "long beat": None,
    "pause": None,
    "long pause": None,
    "trembling": "Speak with a trembling, shaky voice",
    "nervously": "Speak nervously and hesitantly",
    "coldly": "Speak in a cold, detached tone",
    "tenderly": "Speak tenderly and warmly",
    "re: phone": "Speak as if talking on the phone",
    "into phone": "Speak as if talking on the phone",
    "on phone": "Speak as if talking on the phone",
}


def _parse_parenthetical(text: str) -> tuple[bool, Optional[str]]:
    clean = text.strip().strip("()").strip().lower()
    if clean in PARENTHETICAL_TO_INSTRUCT:
        val = PARENTHETICAL_TO_INSTRUCT[clean]
        return (val is None), val
    for kw, instruct in PARENTHETICAL_TO_INSTRUCT.items():
        if kw in clean:
            return (instruct is None), instruct
    return False, clean.capitalize()


def _split_long_text(text: str, max_chars: int = MAX_CHARS_PER_JOB) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks: list[str] = []
    current = ""
    for s in sentences:
        if current and len(current) + len(s) + 1 > max_chars:
            chunks.append(current.strip())
            current = s
        else:
            current = f"{current} {s}" if current else s
    if current.strip():
        chunks.append(current.strip())
    result: list[str] = []
    for c in chunks:
        if len(c) <= max_chars:
            result.append(c)
        else:
            parts = re.split(r'(?<=,)\s+', c)
            buf = ""
            for p in parts:
                if buf and len(buf) + len(p) + 1 > max_chars:
                    result.append(buf.strip())
                    buf = p
                else:
                    buf = f"{buf} {p}" if buf else p
            if buf.strip():
                result.append(buf.strip())
    return result or [text]


def _get_voice(character: Optional[str], casting: CastingResult) -> tuple[str, str, str, str]:
    """Returns (voice_id, voice_type, instruct, gender_hint)."""
    if character and character in casting.roles:
        role = casting.roles[character]
        return role.voice_id, role.voice_type, role.instruct_default, role.gender_hint
    return (
        casting.narrator_voice_id,
        casting.narrator_voice_type,
        casting.narrator_instruct,
        "unknown",
    )


def script_to_tts_jobs(script: Script, casting: CastingResult) -> list[TTSJob]:
    jobs: list[TTSJob] = []
    job_counter = 0
    current_character: Optional[str] = None
    pending_instruct: Optional[str] = None

    def make_job(text, element_ids, scene, element_type, character, instruct_override=None):
        nonlocal job_counter
        voice_id, voice_type, base_instruct, gender_hint = _get_voice(character, casting)
        # instruct_override from parentheticals augments but doesn't erase the voice description
        if instruct_override:
            # Prepend the delivery note to the voice description so VD model sees both
            instruct = f"{instruct_override}. {base_instruct}" if base_instruct else instruct_override
        else:
            instruct = base_instruct
        for chunk_text in _split_long_text(text):
            job_counter += 1
            jobs.append(TTSJob(
                job_id=f"j{job_counter:04d}",
                element_ids=element_ids,
                text=chunk_text,
                voice_id=voice_id,
                voice_type=voice_type,
                instruct=instruct,
                scene=scene or 0,
                element_type=element_type,
                character=character,
            ))

    for elem in script.elements:
        if elem.type == "slug":
            current_character = None
            pending_instruct = None
            make_job(elem.text, [elem.id], elem.scene, "slug", None,
                     instruct_override="Announce clearly and briefly")

        elif elem.type == "action":
            current_character = None
            pending_instruct = None
            make_job(elem.text, [elem.id], elem.scene, "action", None,
                     instruct_override="Read quickly and matter-of-factly")

        elif elem.type == "character":
            current_character = elem.character_name or elem.text.strip()
            pending_instruct = None

        elif elem.type == "parenthetical":
            is_silence, instruct = _parse_parenthetical(elem.text)
            if is_silence:
                job_counter += 1
                jobs.append(TTSJob(
                    job_id=f"j{job_counter:04d}",
                    element_ids=[elem.id],
                    text="",
                    voice_id="silence",
                    voice_type="silence",
                    instruct="",
                    scene=elem.scene or 0,
                    element_type="parenthetical",
                    character=current_character,
                ))
            else:
                pending_instruct = instruct

        elif elem.type == "dialogue":
            instruct = pending_instruct
            pending_instruct = None
            make_job(elem.text, [elem.id], elem.scene, "dialogue", current_character,
                     instruct_override=instruct)

        elif elem.type == "transition":
            current_character = None
            pending_instruct = None
            make_job(elem.text, [elem.id], elem.scene, "transition", None,
                     instruct_override="Announce briefly")

    return jobs
