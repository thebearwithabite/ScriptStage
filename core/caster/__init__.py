"""Character extraction, scoring, and voice assignment."""

from .characters import normalize_character_name, suggest_aliases, merge_characters, infer_gender
from .scoring import compute_prominence
from .voice_inventory import get_voice_inventory
from .assigner import build_cooccurrence_matrix, assign_voices
from .voice_designer import generate_voice_description, generate_narrator_description, NAMED_OVERRIDES
