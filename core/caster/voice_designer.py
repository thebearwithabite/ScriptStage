"""Generate natural language voice descriptions for VoiceDesign TTS.

Pure Python, zero LLM. Heuristics from character stats, name analysis,
dialogue tone, and prominence tier.
"""

from __future__ import annotations

import re
from core.models import Character, Script, ScriptElement

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NARRATOR_DESCRIPTION = (
    "A calm, measured narrator voice — clear, neutral, and unhurried, "
    "with the steady authority of a storyteller"
)

_GENDER_NOUN = {
    "male": "male",
    "female": "female",
    "unknown": "androgynous",
}

# Age / archetype hints keyed on substrings in the uppercase character name
# (key, age_phrase, personality_hint)
_NAME_AGE_HINTS: list[tuple[str, str, str]] = [
    ("YOUNG ",     "teenage or early 20s", "young and earnest"),
    ("OLD ",       "late 60s-70s",         "weathered and slow-spoken"),
    ("LITTLE ",    "around 8-10 years old","bright and childlike"),
    ("JUNIOR",     "teenage",              "young and slightly awkward"),
    ("BABY",       "infant",               ""),
    ("GRANDMA",    "70s",                  "warm and grandmotherly"),
    ("GRANDPA",    "70s",                  "gravelly and grandpaternal"),
    ("GIRL",       "8-14 years old",       "light and curious"),
    ("BOY",        "8-14 years old",       "bright and excitable"),
    ("KID",        "around 10",            "childlike and energetic"),
    ("TEEN",       "mid-teens",            "self-conscious and searching"),
    ("DOCTOR",     "40s-50s",              "clinical and measured"),
    ("OFFICER",    "30s-50s",              "firm and procedural"),
    ("DETECTIVE",  "40s-50s",              "dry and world-weary"),
    ("SERGEANT",   "30s-50s",              "clipped and authoritative"),
    ("CAPTAIN",    "40s-50s",              "commanding"),
    ("GENERAL",    "50s-60s",              "commanding and deliberate"),
    ("COLONEL",    "50s-60s",              "military and precise"),
    ("SOLDIER",    "20s-30s",              "terse and alert"),
    ("PROFESSOR",  "50s-60s",              "scholarly and deliberate"),
    ("TEACHER",    "30s-50s",              "clear and patient"),
    ("OPERATOR",   "30s-40s",              "professional and neutral"),
    ("DISPATCHER", "30s-40s",              "calm and procedural"),
    ("ANNOUNCER",  "30s-50s",              "broadcast-quality and polished"),
    ("PREACHER",   "50s-60s",              "resonant and oratorical"),
    ("PRIEST",     "40s-60s",              "hushed and reverent"),
    ("JUDGE",      "50s-60s",              "stern and deliberate"),
    ("LAWYER",     "30s-50s",              "precise and persuasive"),
    ("REPORTER",   "30s-40s",              "brisk and professional"),
    ("BUTLER",     "50s-60s",              "formal and clipped"),
    ("NURSE",      "30s-40s",              "warm and efficient"),
    ("GUARD",      "30s-40s",              "terse"),
    ("DRIVER",     "30s-50s",              "casual and working-class"),
    ("WOMAN",      "30s-40s",              ""),
    ("MAN",        "30s-40s",              ""),
    ("VOICE",      "adult",               "disembodied or heard offscreen"),
]

# Specific character overrides — populated per-project by name
# These are for The Unfinished Swan specifically but also serve as examples
NAMED_OVERRIDES: dict[str, str] = {
    "MONROE": (
        "A warm, wry male voice in his mid-30s — a painter who has weathered real loss. "
        "Naturally expressive, alternates between dry humor and genuine tenderness. "
        "Mid-range pitch, slight rasp, unhurried pacing."
    ),
    "GILLY": (
        "A bright, earnest female voice in her late 20s to early 30s — curious, kind, "
        "with playful warmth and quiet intelligence. Clear diction, light cadence, "
        "naturally engaging."
    ),
    "AURORA": (
        "A gentle, ethereal female voice — soft and slightly otherworldly, as if heard "
        "from a dream. Melodic and unhurried, with a faint sense of distance."
    ),
    "GRANT": (
        "A gruff, no-nonsense male voice in his 40s — practical, plainspoken, and a "
        "little impatient. Lower register, clipped delivery, working-class texture."
    ),
    "YOUNG MONROE": (
        "A bright, earnest young male voice, around 10-12 years old — wide-eyed and "
        "sincere, with a child's open wonder and slight hesitation."
    ),
    "WOMAN\u2019S VOICE": (
        "A warm, slightly distant female voice — as if heard from memory or another room. "
        "Soft and intimate, with an undercurrent of melancholy."
    ),
    "GIRL": (
        "A light, curious young female voice, around 8-12 years old — bright and slightly "
        "breathless, with the energy of childhood."
    ),
    "911 OPERATOR": (
        "A calm, professional female voice — clipped and procedural, trained to stay "
        "neutral under pressure. Flat affect, clear enunciation."
    ),
}


# ---------------------------------------------------------------------------
# Dialogue tone analysis
# ---------------------------------------------------------------------------

def _dialogue_tone(char_name: str, elements: list[ScriptElement]) -> dict:
    """Scan character dialogue for tone cues. Pure text heuristics."""
    lines = [
        e.text for e in elements
        if e.character_name == char_name and e.type == "dialogue"
    ]
    if not lines:
        return {"empty": True}

    text = " ".join(lines)
    text_lower = text.lower()
    total_words = len(text_lower.split())
    n = len(lines)

    # Average words per line
    avg_words = total_words / n if n else 0

    # Punctuation feel
    q_ratio = text.count("?") / n
    ex_ratio = text.count("!") / n
    ell_ratio = text.count("...") / n

    # Vocabulary feel
    casual_words  = {"yeah", "nah", "gonna", "wanna", "kinda", "sorta",
                     "hey", "dude", "man", "like", "whatever", "okay", "ok",
                     "yep", "nope", "alright", "cool"}
    formal_words  = {"indeed", "certainly", "however", "therefore",
                     "nevertheless", "moreover", "henceforth", "thus",
                     "perhaps", "rather", "quite", "shall"}
    emotion_words = {"love", "hate", "fear", "hope", "dream", "please",
                     "sorry", "miss", "need", "want", "feel", "hurt",
                     "happy", "sad", "angry", "scared"}

    words_set = set(re.findall(r"[a-z']+", text_lower))

    return {
        "empty":         False,
        "avg_words":     avg_words,
        "terse":         avg_words < 8 and n >= 3,
        "verbose":       avg_words > 25,
        "inquisitive":   q_ratio > 0.35,
        "excitable":     ex_ratio > 0.25,
        "hesitant":      ell_ratio > 0.20,
        "casual":        bool(casual_words & words_set),
        "formal":        bool(formal_words & words_set),
        "emotional":     bool(emotion_words & words_set),
        "n_lines":       n,
    }


# ---------------------------------------------------------------------------
# Description builder
# ---------------------------------------------------------------------------

def _age_and_hint_from_name(name: str) -> tuple[str, str]:
    """Check name against archetype table. Returns (age_phrase, personality_hint)."""
    upper = name.upper()
    for key, age, hint in _NAME_AGE_HINTS:
        if key in upper:
            return age, hint
    return "", ""


def generate_voice_description(
    char: Character,
    script: Script,
    prominence: float,
) -> str:
    """Build a natural-language voice description for VoiceDesign TTS.

    Returns a 1–3 sentence string suitable as the `instruct` argument to
    `Qwen3TTSModel.generate_voice_design(text, instruct=..., language="english")`.
    """
    name = char.name

    # Named overrides win immediately
    if name in NAMED_OVERRIDES:
        return NAMED_OVERRIDES[name]

    gender = char.gender_hint or "unknown"
    gender_noun = _GENDER_NOUN.get(gender, "androgynous")

    # Prominence tier
    if prominence >= 0.5:
        tier_label = "lead"
        tier_depth = "deeply expressive and emotionally present"
    elif prominence >= 0.15:
        tier_label = "support"
        tier_depth = "clear and distinctly characterful"
    else:
        tier_label = "minor"
        tier_depth = "brief but immediately recognizable"

    # Age / archetype from name
    age_phrase, archetype_hint = _age_and_hint_from_name(name)

    # Dialogue tone
    tone = _dialogue_tone(name, script.elements)

    # Build age string
    if age_phrase:
        age_str = f", {age_phrase}"
    else:
        # Default age by prominence and gender
        if prominence >= 0.5:
            age_str = ", in their 30s"
        elif prominence >= 0.15:
            age_str = ", in their 30s-50s"
        else:
            age_str = ", adult"

    # Tone descriptors
    tone_descriptors: list[str] = []
    if not tone.get("empty"):
        if tone["casual"]:
            tone_descriptors.append("relaxed and conversational")
        elif tone["formal"]:
            tone_descriptors.append("measured and articulate")

        if tone["emotional"]:
            tone_descriptors.append("emotionally resonant")

        if tone["terse"]:
            tone_descriptors.append("economical and clipped")
        elif tone["verbose"]:
            tone_descriptors.append("expansive and flowing")

        if tone["inquisitive"]:
            tone_descriptors.append("inquisitive")
        if tone["excitable"]:
            tone_descriptors.append("energetic")
        if tone["hesitant"]:
            tone_descriptors.append("with a hesitant, searching quality")

    # Archetype hint from name
    if archetype_hint:
        tone_descriptors.insert(0, archetype_hint)

    # Assemble
    tone_str = ""
    if tone_descriptors:
        tone_str = " — " + ", ".join(tone_descriptors[:3])

    description = (
        f"A {gender_noun} voice{age_str}{tone_str}. "
        f"Delivery is {tier_depth}."
    )
    return description


def generate_narrator_description() -> str:
    """Return the narrator voice description."""
    return NARRATOR_DESCRIPTION
