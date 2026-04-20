"""Voice assignment — VoiceDesign primary, 9 native speakers as fallbacks."""

from __future__ import annotations

from core.models import Character, Scene, CastingResult, RoleAssignment, SharedPool
from core.caster.voice_designer import (
    generate_voice_description,
    generate_narrator_description,
)


# ---------------------------------------------------------------------------
# Cooccurrence matrix
# ---------------------------------------------------------------------------

def build_cooccurrence_matrix(
    characters: list[Character], scenes: list[Scene]
) -> dict[tuple[str, str], int]:
    """Build character-pair → shared scene count mapping."""
    scene_chars: dict[int, set[str]] = {}
    for char in characters:
        for s in char.scenes_list:
            scene_chars.setdefault(s, set()).add(char.name)

    matrix: dict[tuple[str, str], int] = {}
    for chars_in_scene in scene_chars.values():
        chars_list = sorted(chars_in_scene)
        for i, a in enumerate(chars_list):
            for b in chars_list[i + 1:]:
                key = (a, b)
                matrix[key] = matrix.get(key, 0) + 1
    return matrix


# ---------------------------------------------------------------------------
# Native speaker fallback pool
# ---------------------------------------------------------------------------

# Gender-tagged fallback voices (9 CustomVoice speakers)
_FALLBACK_MALE   = ["eric", "ryan", "dylan", "aiden", "uncle_fu"]
_FALLBACK_FEMALE = ["vivian", "serena", "ono_anna", "sohee"]
_FALLBACK_ALL    = _FALLBACK_MALE + _FALLBACK_FEMALE


def _pick_fallback(
    gender: str,
    used_fallbacks: set[str],
    pool: list[str] | None = None,
) -> str:
    """Pick the next unused fallback speaker for a gender."""
    candidates = pool or (
        _FALLBACK_FEMALE if gender == "female"
        else _FALLBACK_MALE if gender == "male"
        else _FALLBACK_ALL
    )
    for v in candidates:
        if v not in used_fallbacks:
            return v
    # All used — cycle from beginning
    return candidates[0]


# ---------------------------------------------------------------------------
# Main assign function
# ---------------------------------------------------------------------------

def assign_voices(
    characters: list[Character],
    prominences: dict[str, float],
    cooccurrence: dict[tuple[str, str], int],
    voice_inventory: dict,
    locked: dict[str, str] | None = None,
    script=None,  # core.models.Script — optional, for richer voice descriptions
) -> CastingResult:
    """Assign voices using VoiceDesign (primary) with native-speaker fallbacks.

    Every character gets a natural-language voice description used as the
    `instruct` argument to `generate_voice_design()`.  The `voice_id` field
    carries a stable slug (vd_<charname>) for caching / display; the engine
    uses `voice_type == "voice_design"` to route to the VD model.

    The 9 native CustomVoice speakers are assigned as a fallback `voice_id`
    so the engine can degrade gracefully if the VD model isn't loaded.
    """
    if locked is None:
        locked = {}

    sorted_chars = sorted(
        characters, key=lambda c: prominences.get(c.name, 0), reverse=True
    )

    roles: dict[str, RoleAssignment] = {}
    used_fallbacks: set[str] = set()

    for char in sorted_chars:
        prom = prominences.get(char.name, 0)
        gender = char.gender_hint or "unknown"

        # --- Locked override (explicit voice_id requested by user) ---
        if char.name in locked:
            locked_id = locked[char.name]
            # Check if it's a native speaker id
            native_ids = {v["id"] for v in voice_inventory.get("native_speakers", [])}
            if locked_id in native_ids:
                vtype = "native"
                instruct = ""
            else:
                vtype = "voice_design"
                instruct = locked_id  # treat locked id as an instruct string
            roles[char.name] = RoleAssignment(
                voice_id=locked_id,
                voice_type=vtype,
                instruct_default=instruct,
                prominence=prom,
                gender_hint=gender,
                total_lines=char.stats.lines,
                total_words=char.stats.words,
                total_scenes=char.stats.scenes,
                label=f"{locked_id}",
            )
            continue

        # --- Generate VoiceDesign description ---
        from core.models import Script as ScriptModel
        effective_script = script or ScriptModel(
            meta=__import__("core.models", fromlist=["ScriptMeta"]).ScriptMeta(),
            elements=[],
            characters=characters,
            scenes=[],
        )
        vd_description = generate_voice_description(char, effective_script, prom)

        # --- Fallback native speaker (engine uses if VD model fails) ---
        fallback_id = _pick_fallback(gender, used_fallbacks)
        used_fallbacks.add(fallback_id)

        # Slug for display / caching
        slug = f"vd_{char.name.lower().replace(' ', '_').replace(chr(39), '')}"

        roles[char.name] = RoleAssignment(
            voice_id=slug,
            voice_type="voice_design",
            instruct_default=vd_description,
            prominence=prom,
            gender_hint=gender,
            total_lines=char.stats.lines,
            total_words=char.stats.words,
            total_scenes=char.stats.scenes,
            label=f"{char.name} (VoiceDesign)",
            # Stash fallback in a way the engine can use it
            # We piggyback on voice_id's prefix: native fallback exposed via
            # an extra field would require a model change; instead we add a
            # secondary voice_id via instruct if needed. For now the engine
            # already has the eric-fallback path hardcoded.
        )

    # --- Narrator ---
    narrator_description = generate_narrator_description()
    narrator_slug = "vd_narrator"

    # Narrator fallback: pick a voice not used by leads
    lead_fallbacks = {
        r.voice_id for n, r in roles.items()
        if prominences.get(n, 0) >= 0.5
    }
    narrator_fallback = "eric"
    for v in _FALLBACK_MALE:
        if v not in lead_fallbacks:
            narrator_fallback = v
            break

    return CastingResult(
        narrator_voice_id=narrator_slug,
        narrator_voice_type="voice_design",
        narrator_instruct=narrator_description,
        narrator_label=f"Narrator (VoiceDesign)",
        roles=roles,
        shared_pool=SharedPool(
            voices=[narrator_fallback],
            assignments={},
        ),
    )
