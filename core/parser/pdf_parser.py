"""PDF screenplay parser using PyMuPDF (fitz).

Extracts text spans with bounding-box positions, clusters x-offsets to
detect screenplay formatting, and classifies lines into script elements.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

import fitz  # PyMuPDF

from ..models import (
    Character,
    CharacterStats,
    Scene,
    Script,
    ScriptElement,
    ScriptMeta,
)
from ..caster.characters import infer_gender

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

SLUG_RE = re.compile(
    r"^\s*(INT\.|EXT\.|INT/EXT\.|INT\./EXT\.|I/E\.|PHOTO\b|FLASHBACK)",
    re.IGNORECASE,
)
TRANSITION_RE = re.compile(
    r"(FADE IN:|FADE OUT\.?|FADE TO:|CUT TO:|SMASH CUT|DISSOLVE TO:)\s*$",
    re.IGNORECASE,
)
CONT_MORE_RE = re.compile(
    r"^\s*\((MORE|CONT(?:'D|INUED|\u2019D))\)\s*$", re.IGNORECASE,
)
CONTINUED_HEADER_RE = re.compile(r"^\s*CONTINUED:?\s*$", re.IGNORECASE)

# Character-cue extension stripping — handles smart quotes
_APOS = "'\u2019\u2018\u02bc"
CHAR_EXT_RE = re.compile(
    r"\s*\((?:CONT[" + _APOS + r"]D|CONTINUED|V\.O\.|O\.S\.|O\.C\."
    r"|PRE-?LAP|ON (?:SCREEN|PHONE|TV))\)\s*",
    re.IGNORECASE,
)

PAGE_NUM_RE = re.compile(r"^\s*\d+\.?\s*$")
TITLE_HINT_RE = re.compile(
    r"written\s+by|screenplay\s+by|teleplay\s+by", re.IGNORECASE,
)

BOLD_FLAG = 1 << 4


# ---------------------------------------------------------------------------
# Internal data types
# ---------------------------------------------------------------------------

@dataclass
class _Span:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    bold: bool
    size: float
    page: int


@dataclass
class _Line:
    y: float
    spans: list[_Span] = field(default_factory=list)
    x0: float = 0.0
    text: str = ""
    bold: bool = False
    page: int = 0

    def finalise(self):
        self.spans.sort(key=lambda s: s.x0)
        self.x0 = self.spans[0].x0
        self.text = "".join(s.text for s in self.spans).rstrip()
        self.bold = any(s.bold and s.text.strip() for s in self.spans)
        self.page = self.spans[0].page


# ---------------------------------------------------------------------------
# X-offset clustering
# ---------------------------------------------------------------------------

def _cluster_offsets(
    x_values: list[float], *, tol: float = 12.0, max_k: int = 4,
) -> list[float]:
    """Find the dominant x-offset clusters in screenplay text.

    Counts x-values rounded to int, filters to significant frequencies,
    then merges nearby values into buckets.  Returns up to *max_k*
    cluster centres sorted by position.
    """
    if not x_values:
        return []

    counts: Counter[int] = Counter()
    for x in x_values:
        counts[round(x)] += 1

    # Only consider values with meaningful frequency
    min_count = max(5, len(x_values) // 200)
    candidates = sorted(
        [(k, n) for k, n in counts.items() if n >= min_count],
        key=lambda kv: kv[0],
    )

    # Greedily merge into buckets (nearest-centre matching)
    buckets: list[tuple[float, int]] = []
    for k, n in candidates:
        best_bi = -1
        best_dist = tol
        for bi, (bc, _bn) in enumerate(buckets):
            d = abs(k - bc)
            if d < best_dist:
                best_dist = d
                best_bi = bi
        if best_bi >= 0:
            bc, bn = buckets[best_bi]
            new_n = bn + n
            buckets[best_bi] = ((bc * bn + k * n) / new_n, new_n)
        else:
            buckets.append((float(k), n))

    # Take the top max_k by count
    buckets.sort(key=lambda b: -b[1])
    return sorted(b[0] for b in buckets[:max_k])


def _nearest_cluster(x: float, centres: list[float]) -> int:
    best_i, best_d = 0, abs(x - centres[0])
    for i, c in enumerate(centres[1:], 1):
        d = abs(x - c)
        if d < best_d:
            best_d = d
            best_i = i
    return best_i


def _assign_roles(centres: list[float]) -> dict[int, str]:
    """Map cluster indices to screenplay roles by position.

    Standard ordering (left to right):
      action — dialogue — parenthetical — character cue
    """
    n = len(centres)
    roles: dict[int, str] = {}
    if n == 0:
        return roles
    roles[0] = "action"
    if n >= 2:
        roles[n - 1] = "character"
    if n >= 3:
        roles[n - 2] = "parenthetical"
    if n >= 4:
        roles[n - 3] = "dialogue"
    if n >= 5:
        for i in range(1, n - 3):
            roles[i] = "action"
    return roles


# ---------------------------------------------------------------------------
# Title detection
# ---------------------------------------------------------------------------

def _detect_title(lines: list[_Line]) -> Optional[str]:
    page0 = [ln for ln in lines if ln.page == 0]
    if not any(TITLE_HINT_RE.search(ln.text) for ln in page0):
        return None
    for ln in page0:
        t = ln.text.strip()
        if t and not TITLE_HINT_RE.search(t) and len(t) > 2 and not PAGE_NUM_RE.match(t):
            return t
    return None


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_pdf(file_path: str) -> Script:
    """Parse a PDF screenplay and return a Script model."""
    doc = fitz.open(file_path)
    page_count = len(doc)

    # --- Scanned-PDF check ---
    total_chars = sum(len(page.get_text()) for page in doc)
    if page_count > 0 and total_chars / page_count < 10:
        doc.close()
        return Script(
            meta=ScriptMeta(
                title="(scanned PDF \u2014 OCR required)",
                page_count_estimate=page_count,
                source_format="pdf",
            )
        )

    # --- Extract spans ---
    all_spans: list[_Span] = []
    for pi, page in enumerate(doc):
        d = page.get_text("dict")
        for block in d.get("blocks", []):
            if "lines" not in block:
                continue
            for ln in block["lines"]:
                for sp in ln["spans"]:
                    txt = sp["text"]
                    if not txt:
                        continue
                    bb = sp["bbox"]
                    all_spans.append(_Span(
                        x0=bb[0], y0=bb[1], x1=bb[2], y1=bb[3],
                        text=txt, bold=bool(sp["flags"] & BOLD_FLAG),
                        size=sp["size"], page=pi,
                    ))

    # --- Group spans into lines (same page + y within tolerance) ---
    Y_TOL = 3.0
    lines: list[_Line] = []
    for sp in all_spans:
        merged = False
        for ln in reversed(lines[-30:]):
            if ln.page == sp.page and abs(ln.y - sp.y0) < Y_TOL:
                ln.spans.append(sp)
                merged = True
                break
        if not merged:
            new_line = _Line(y=sp.y0, page=sp.page)
            new_line.spans.append(sp)
            lines.append(new_line)

    for ln in lines:
        ln.finalise()
    lines.sort(key=lambda l: (l.page, l.y))

    # --- Detect title ---
    title = _detect_title(lines) or "(untitled)"

    # --- Filter header/footer noise ---
    content_lines: list[_Line] = []
    for ln in lines:
        t = ln.text.strip()
        if not t:
            continue
        # Skip title page entirely
        if ln.page == 0:
            continue
        # Page numbers / revision headers at top of page
        if ln.y < 55:
            upper = t.upper()
            if PAGE_NUM_RE.match(t) or any(
                kw in upper for kw in ("POLISH", "DRAFT", "REVISION")
            ):
                continue
        # (CONTINUED) / (MORE) markers
        if CONT_MORE_RE.match(t) or CONTINUED_HEADER_RE.match(t):
            continue
        content_lines.append(ln)

    # --- Cluster x-offsets ---
    x_offsets = [ln.x0 for ln in content_lines if len(ln.text.strip()) > 1]
    centres = _cluster_offsets(x_offsets)
    roles = _assign_roles(centres)

    # --- Classify lines into elements ---
    elements: list[ScriptElement] = []
    eid = 0
    current_scene = 0
    current_char: Optional[str] = None
    char_data: dict[str, dict] = {}  # name -> {lines, words, scenes: set}

    for ln in content_lines:
        t = ln.text.strip()
        if not t:
            continue

        ci = _nearest_cluster(ln.x0, centres) if centres else 0
        role = roles.get(ci, "action")

        # --- Transition ---
        if TRANSITION_RE.search(t):
            eid += 1
            elements.append(ScriptElement(
                id=f"e{eid}", type="transition", text=t, scene=current_scene,
            ))
            continue

        # --- Slug line ---
        if role == "action" and ln.bold and SLUG_RE.match(t):
            current_scene += 1
            current_char = None
            eid += 1
            elements.append(ScriptElement(
                id=f"e{eid}", type="slug", text=t, scene=current_scene,
            ))
            continue

        # --- Character cue ---
        if role == "character":
            clean_name = CHAR_EXT_RE.sub("", t).strip().upper()
            if (
                clean_name
                and not clean_name.endswith(":")
                and not clean_name.endswith(".")
                and not clean_name.endswith("!")
                and not TRANSITION_RE.search(clean_name)
                and len(clean_name) < 40
                and clean_name not in ("THE END",)
            ):
                current_char = clean_name
                eid += 1
                elements.append(ScriptElement(
                    id=f"e{eid}", type="character", text=t,
                    scene=current_scene, character_name=current_char,
                ))
                if current_char not in char_data:
                    char_data[current_char] = {
                        "lines": 0, "words": 0, "scenes": set(),
                    }
                continue

        # --- Parenthetical ---
        if role == "parenthetical" or (t.startswith("(") and t.endswith(")")):
            eid += 1
            elements.append(ScriptElement(
                id=f"e{eid}", type="parenthetical", text=t,
                scene=current_scene, character_name=current_char,
            ))
            continue

        # --- Dialogue ---
        if role == "dialogue" and current_char:
            eid += 1
            elements.append(ScriptElement(
                id=f"e{eid}", type="dialogue", text=t,
                scene=current_scene, character_name=current_char,
            ))
            if current_char in char_data:
                char_data[current_char]["lines"] += 1
                char_data[current_char]["words"] += len(t.split())
                char_data[current_char]["scenes"].add(current_scene)
            continue

        # --- Action (default) ---
        eid += 1
        elements.append(ScriptElement(
            id=f"e{eid}", type="action", text=t, scene=current_scene,
        ))
        current_char = None

    # --- Build Character list (deduplicated, sorted by word count) ---
    # Pre-compute char element indices for gender inference
    char_element_map: dict[str, list[int]] = {}
    for i, el in enumerate(elements):
        if el.character_name and el.type in ("character", "dialogue"):
            char_element_map.setdefault(el.character_name, []).append(i)

    characters: list[Character] = []
    for name, stats in sorted(char_data.items(), key=lambda kv: -kv[1]["words"]):
        scene_set: set = stats["scenes"]
        gender = infer_gender(name, elements, char_element_map.get(name, []))
        characters.append(Character(
            name=name,
            stats=CharacterStats(
                lines=stats["lines"],
                words=stats["words"],
                scenes=len(scene_set),
            ),
            scenes_list=sorted(scene_set),
            first_scene=min(scene_set) if scene_set else 0,
            last_scene=max(scene_set) if scene_set else 0,
            gender_hint=gender,
        ))

    # --- Build Scene list ---
    scenes: list[Scene] = []
    slug_elements = [e for e in elements if e.type == "slug"]
    for i, se in enumerate(slug_elements):
        if i + 1 < len(slug_elements):
            next_slug_id = slug_elements[i + 1].id
            end_id = se.id
            for e in elements:
                if e.id == next_slug_id:
                    break
                end_id = e.id
        else:
            end_id = elements[-1].id if elements else se.id
        scenes.append(Scene(
            scene=se.scene or (i + 1),
            slug=se.text,
            start_element=se.id,
            end_element=end_id,
        ))

    doc.close()

    return Script(
        meta=ScriptMeta(
            title=title,
            page_count_estimate=page_count,
            source_format="pdf",
        ),
        elements=elements,
        characters=characters,
        scenes=scenes,
    )
