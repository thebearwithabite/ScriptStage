"""Character extraction, normalization, alias detection, and gender inference."""

from __future__ import annotations

import re
from core.models import Character, Script, ScriptElement

# Extensions to strip from character cues
_EXTENSIONS = re.compile(
    r"\s*\("
    r"(?:CONT'?D|V\.O\.|O\.S\.|O\.C\.|PRE-LAP|CONT'D;\s*V\.O\.|MORE)"
    r"\)\s*",
    re.IGNORECASE,
)

_AGE_PREFIXES = ("YOUNG ", "OLD ", "LITTLE ")


def normalize_character_name(raw: str) -> str:
    """Strip extensions, whitespace, and trailing punctuation from a character cue."""
    name = _EXTENSIONS.sub("", raw)
    name = name.strip().strip(":").strip()
    name = re.sub(r"\s{2,}", " ", name)
    return name.upper()


def _levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        return _levenshtein(b, a)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j] + (ca != cb), prev[j + 1] + 1, curr[j] + 1))
        prev = curr
    return prev[-1]


def suggest_aliases(characters: list[Character]) -> list[tuple[str, str]]:
    """Find merge candidates: prefix matches (YOUNG X→X) and near-Levenshtein names.

    Returns list of (source, target) pairs where source should merge into target.
    """
    names = [c.name for c in characters]
    name_set = set(names)
    suggestions: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    # Prefix-based suggestions
    for name in names:
        for prefix in _AGE_PREFIXES:
            if name.startswith(prefix):
                base = name[len(prefix):]
                if base in name_set and (name, base) not in seen:
                    suggestions.append((name, base))
                    seen.add((name, base))

    # Levenshtein-based suggestions
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if (a, b) in seen or (b, a) in seen:
                continue
            if _levenshtein(a, b) < 3 and a != b:
                src, tgt = (a, b) if len(a) < len(b) else (b, a)
                if (src, tgt) not in seen:
                    suggestions.append((src, tgt))
                    seen.add((src, tgt))

    return suggestions


def merge_characters(script: Script, source: str, target: str) -> Script:
    """Merge character `source` into `target`, updating all references."""
    source_upper = source.upper()
    target_upper = target.upper()

    src_char: Character | None = None
    tgt_char: Character | None = None
    for c in script.characters:
        if c.name == source_upper:
            src_char = c
        if c.name == target_upper:
            tgt_char = c

    if src_char is None or tgt_char is None:
        return script

    # Merge stats
    tgt_char.stats.lines += src_char.stats.lines
    tgt_char.stats.words += src_char.stats.words
    merged_scenes = sorted(set(tgt_char.scenes_list + src_char.scenes_list))
    tgt_char.scenes_list = merged_scenes
    tgt_char.stats.scenes = len(merged_scenes)
    tgt_char.first_scene = min(tgt_char.first_scene, src_char.first_scene)
    tgt_char.last_scene = max(tgt_char.last_scene, src_char.last_scene)
    if source_upper not in tgt_char.aliases:
        tgt_char.aliases.append(source_upper)

    # Update elements
    for el in script.elements:
        if el.type == "character" and el.character_name == source_upper:
            el.character_name = target_upper
            el.text = target_upper

    # Remove source from character list
    script.characters = [c for c in script.characters if c.name != source_upper]

    return script


_MALE_PRONOUNS = re.compile(r"\b(he|him|his|himself)\b", re.IGNORECASE)
_FEMALE_PRONOUNS = re.compile(r"\b(she|her|hers|herself)\b", re.IGNORECASE)


def infer_gender(
    character_name: str,
    elements: list[ScriptElement],
    char_element_indices: list[int],
) -> str:
    """Scan action lines near character's dialogue for gendered pronouns.

    Returns "male", "female", or "unknown".
    """
    male_score = 0
    female_score = 0

    for idx in char_element_indices:
        for offset in range(-3, 4):
            check_idx = idx + offset
            if check_idx < 0 or check_idx >= len(elements):
                continue
            el = elements[check_idx]
            if el.type != "action":
                continue
            male_score += len(_MALE_PRONOUNS.findall(el.text))
            female_score += len(_FEMALE_PRONOUNS.findall(el.text))

    if male_score == 0 and female_score == 0:
        return "unknown"
    if male_score > female_score * 1.5:
        return "male"
    if female_score > male_score * 1.5:
        return "female"
    return "unknown"
