"""ScriptStage core data models — Pydantic v2."""

from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class CharacterStats(BaseModel):
    lines: int = 0
    words: int = 0
    scenes: int = 0


class ScriptElement(BaseModel):
    id: str
    type: str  # slug, action, character, parenthetical, dialogue, transition
    text: str
    scene: Optional[int] = None
    character_name: Optional[str] = None  # normalized name


class Character(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    stats: CharacterStats = Field(default_factory=CharacterStats)
    scenes_list: list[int] = Field(default_factory=list)
    gender_hint: str = "unknown"
    first_scene: int = 0
    last_scene: int = 0


class Scene(BaseModel):
    scene: int
    slug: str
    start_element: str
    end_element: str = ""


class ScriptMeta(BaseModel):
    title: Optional[str] = None
    page_count_estimate: int = 0
    source_format: str = "unknown"
    author: Optional[str] = None


class Script(BaseModel):
    meta: ScriptMeta
    elements: list[ScriptElement] = Field(default_factory=list)
    characters: list[Character] = Field(default_factory=list)
    scenes: list[Scene] = Field(default_factory=list)


class VoiceProfile(BaseModel):
    id: str
    gender: str = "unknown"
    age: str = "adult"
    quality: str = ""
    tier: int = 1
    label: str = ""
    description: str = ""  # for voice_design


class RoleAssignment(BaseModel):
    voice_id: str
    voice_type: str = "native"  # native | voice_design
    instruct_default: str = ""
    label: str = ""
    prominence: float = 0.0
    gender_hint: str = "unknown"
    total_lines: int = 0
    total_words: int = 0
    total_scenes: int = 0


class SharedPool(BaseModel):
    voices: list[str] = Field(default_factory=list)
    assignments: dict[str, str] = Field(default_factory=dict)


class CastingResult(BaseModel):
    narrator_voice_id: str = "eric"
    narrator_voice_type: str = "native"
    narrator_instruct: str = "Speak in a calm, neutral, measured narration voice"
    narrator_label: str = "Narrator (Eric)"
    roles: dict[str, RoleAssignment] = Field(default_factory=dict)
    shared_pool: SharedPool = Field(default_factory=SharedPool)


class TTSJob(BaseModel):
    job_id: str
    element_ids: list[str] = Field(default_factory=list)
    text: str
    voice_id: str
    voice_type: str = "native"  # native | voice_design | narrator
    instruct: str = ""
    scene: int = 0
    element_type: str = "dialogue"  # dialogue | action | slug | parenthetical
    character: Optional[str] = None  # None for narrator lines


class ChunkResult(BaseModel):
    job_id: str
    wav_path: str
    duration_ms: int = 0
    trailing_silence_ms: int = 0
    text: str = ""
    character: Optional[str] = None
    element_ids: list[str] = Field(default_factory=list)
    scene: int = 0
    element_type: str = ""


class CaptionEntry(BaseModel):
    id: str
    start_ms: int
    end_ms: int
    text: str
    speaker: str
    element_ids: list[str] = Field(default_factory=list)
    scene: int = 0
    type: str = ""
