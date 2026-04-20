"""Prominence scoring for screenplay characters."""

from __future__ import annotations

from core.models import Character


def compute_prominence(characters: list[Character], total_scenes: int) -> dict[str, float]:
    """Compute normalized prominence scores for all characters.

    Weighted formula:
        0.35 * word_share + 0.20 * line_share + 0.20 * scene_share
        + 0.15 * arc_spread + 0.05 * act_presence + 0.05 * density

    Normalized so top character = 1.0.
    """
    if not characters or total_scenes == 0:
        return {}

    total_words = sum(c.stats.words for c in characters)
    max_lines = max((c.stats.lines for c in characters), default=1)
    if total_words == 0:
        total_words = 1
    if max_lines == 0:
        max_lines = 1

    # Act boundaries (3-act structure estimate)
    act1_end = total_scenes * 0.25
    act2_end = total_scenes * 0.75

    raw_scores: dict[str, float] = {}

    for char in characters:
        word_share = char.stats.words / total_words
        line_share = char.stats.lines / max_lines
        scene_share = len(char.scenes_list) / total_scenes

        # Arc spread
        if total_scenes > 1:
            arc_spread = (char.last_scene - char.first_scene) / total_scenes
        else:
            arc_spread = 1.0

        # Act presence
        acts_present = 0
        for s in char.scenes_list:
            if s <= act1_end:
                acts_present |= 1
            elif s <= act2_end:
                acts_present |= 2
            else:
                acts_present |= 4
        act_presence = bin(acts_present).count("1") / 3.0

        # Density
        if char.stats.lines > 0:
            density = min((char.stats.words / char.stats.lines) / 20.0, 1.0)
        else:
            density = 0.0

        raw = (
            0.35 * word_share
            + 0.20 * line_share
            + 0.20 * scene_share
            + 0.15 * arc_spread
            + 0.05 * act_presence
            + 0.05 * density
        )
        raw_scores[char.name] = raw

    max_raw = max(raw_scores.values()) if raw_scores else 1.0
    if max_raw == 0:
        max_raw = 1.0

    return {name: score / max_raw for name, score in raw_scores.items()}
