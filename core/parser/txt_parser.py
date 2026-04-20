"""TXT/Fountain screenplay parser for ScriptStage."""

from __future__ import annotations
import re
from pathlib import Path
from typing import Optional

from core.models import Character, CharacterStats, Scene, Script, ScriptElement, ScriptMeta

_CHAR_SUFFIXES = re.compile(
    r"\s*\("
    r"(?:CONT'D|CONT|CONTINUED|V\.O\.|VO|O\.S\.|OS|O\.C\.|OC|OVER|OFF|INTO PHONE|ON PHONE|FILTERED|PRE-?LAP)"
    r"\)\s*$",
    re.IGNORECASE,
)
_WRITTEN_BY = re.compile(r"(?:written|screenplay|script)\s+by", re.IGNORECASE)
_SLUG_PREFIX = re.compile(r"^(?:INT\.|EXT\.|INT/EXT\.|I/E\.)", re.IGNORECASE)


def _normalize_character(raw: str) -> str:
    name = _CHAR_SUFFIXES.sub("", raw).strip()
    return name.upper()


def _is_allcaps(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def _extract_title(lines: list[str]) -> tuple[Optional[str], Optional[str]]:
    non_blank = []
    for ln in lines:
        if ln.strip():
            non_blank.append(ln.strip())
        if len(non_blank) >= 6:
            break
    if len(non_blank) < 2:
        return None, None
    first_text = non_blank[0]
    for txt in non_blank[1:5]:
        if _WRITTEN_BY.search(txt):
            author = None
            idx = next((j for j, t in enumerate(non_blank) if _WRITTEN_BY.search(t)), None)
            if idx is not None and idx + 1 < len(non_blank):
                author = non_blank[idx + 1]
            return first_text, author
    return None, None


def parse_txt(file_path: str) -> Script:
    text = Path(file_path).read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")

    title, author = _extract_title(lines)
    meta = ScriptMeta(title=title, author=author, source_format="txt",
                      page_count_estimate=max(1, len(lines) // 55))

    elements: list[ScriptElement] = []
    scenes: list[Scene] = []
    char_data: dict[str, dict] = {}  # name -> {lines, words, scenes_list}

    eid = 0
    scene_num = 0
    current_char: Optional[str] = None

    def next_id() -> str:
        nonlocal eid
        eid += 1
        return f"e{eid}"

    def touch_char(name: str, words: int = 0, is_line: bool = False):
        if name not in char_data:
            char_data[name] = {"lines": 0, "words": 0, "scenes_list": []}
        d = char_data[name]
        if is_line:
            d["lines"] += 1
        d["words"] += words
        if scene_num and scene_num not in d["scenes_list"]:
            d["scenes_list"].append(scene_num)

    i = 0
    n = len(lines)
    while i < n:
        stripped = lines[i].strip()

        if not stripped:
            current_char = None
            i += 1
            continue

        # Forced scene heading
        if stripped.startswith(".") and not stripped.startswith(".."):
            heading = stripped[1:].strip()
            scene_num += 1
            elem_id = next_id()
            elements.append(ScriptElement(id=elem_id, type="slug", text=heading, scene=scene_num))
            scenes.append(Scene(scene=scene_num, slug=heading, start_element=elem_id))
            current_char = None
            i += 1
            continue

        # Forced character
        if stripped.startswith("@"):
            raw_name = stripped[1:].strip()
            norm = _normalize_character(raw_name)
            current_char = norm
            elements.append(ScriptElement(id=next_id(), type="character", text=raw_name, character_name=norm, scene=scene_num))
            touch_char(norm)
            i += 1
            continue

        # Auto scene heading
        if _SLUG_PREFIX.match(stripped):
            scene_num += 1
            elem_id = next_id()
            elements.append(ScriptElement(id=elem_id, type="slug", text=stripped, scene=scene_num))
            scenes.append(Scene(scene=scene_num, slug=stripped, start_element=elem_id))
            current_char = None
            i += 1
            continue

        # Transition
        if stripped.startswith(">"):
            elements.append(ScriptElement(id=next_id(), type="transition", text=stripped[1:].strip(), scene=scene_num))
            current_char = None
            i += 1
            continue

        # Character cue heuristic
        if current_char is None and _is_allcaps(stripped) and len(stripped) < 40 and not stripped.startswith("("):
            j = i + 1
            while j < n and not lines[j].strip():
                j += 1
            if j < n and lines[j].strip() and not _is_allcaps(lines[j].strip()):
                norm = _normalize_character(stripped)
                current_char = norm
                elements.append(ScriptElement(id=next_id(), type="character", text=stripped, character_name=norm, scene=scene_num))
                touch_char(norm)
                i += 1
                continue

        # Parenthetical
        if current_char and stripped.startswith("(") and stripped.endswith(")"):
            elements.append(ScriptElement(id=next_id(), type="parenthetical", text=stripped, character_name=current_char, scene=scene_num))
            i += 1
            continue

        # Dialogue
        if current_char:
            words = len(stripped.split())
            elements.append(ScriptElement(id=next_id(), type="dialogue", text=stripped, character_name=current_char, scene=scene_num))
            touch_char(current_char, words=words, is_line=True)
            i += 1
            continue

        # Action
        elements.append(ScriptElement(id=next_id(), type="action", text=stripped, scene=scene_num))
        i += 1

    # Build Character list
    characters = []
    for name, d in char_data.items():
        sl = sorted(d["scenes_list"])
        characters.append(Character(
            name=name,
            stats=CharacterStats(lines=d["lines"], words=d["words"], scenes=len(sl)),
            scenes_list=sl,
            first_scene=sl[0] if sl else 0,
            last_scene=sl[-1] if sl else 0,
        ))

    # Set end_element on scenes
    for idx, sc in enumerate(scenes):
        if idx + 1 < len(scenes):
            # Find the element just before the next scene's start
            next_start = scenes[idx + 1].start_element
            for ei, el in enumerate(elements):
                if el.id == next_start and ei > 0:
                    sc.end_element = elements[ei - 1].id
                    break
        else:
            sc.end_element = elements[-1].id if elements else sc.start_element

    return Script(meta=meta, elements=elements, characters=characters, scenes=scenes)
