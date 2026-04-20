# ScriptStage — Implementation Plan

> Generated 2026-03-05 from spec analysis + system investigation.
> Reference script: "THE UNFINISHED SWAN" (110-page PDF, Sony/PlayStation Productions)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Gradio Web UI (:7860)                 │
│  Upload → Parse → Cast → Generate → Playback + Captions │
└────────┬──────────┬──────────┬──────────┬───────────────┘
         │          │          │          │
    ┌────▼───┐ ┌────▼───┐ ┌───▼────┐ ┌───▼─────┐
    │ Parser │ │ Caster │ │ Synth  │ │ Player  │
    │ Module │ │ Module │ │ Engine │ │ + Caps  │
    └────┬───┘ └────┬───┘ └───┬────┘ └───┬─────┘
         │          │         │           │
    ┌────▼──────────▼─────────▼───────────▼───┐
    │         Core Data Model (Pydantic)      │
    │   Script → Casting → Chunks → Captions  │
    └─────────────────┬───────────────────────┘
                      │
    ┌─────────────────▼───────────────────────┐
    │     runs/<timestamp>_<name>/            │
    │  parsed_script.json, casting.json,      │
    │  chunks/*.wav, table_read_full.wav,     │
    │  captions.srt, captions.json            │
    └─────────────────────────────────────────┘
```

### Component Breakdown

| Component | Responsibility | Key Dependencies |
|-----------|---------------|-----------------|
| **Parser** | FDX/DOCX/PDF/TXT → structured `Script` model | `lxml`, `python-docx`, `PyMuPDF`, regex |
| **Caster** | Character extraction, alias resolution, voice assignment scoring | numpy (scoring), qwen-tts (voice inventory) |
| **Synthesizer** | Chunk-based TTS generation, assembly, caching | `qwen-tts`, `soundfile`, `pydub`/`ffmpeg` |
| **Caption Engine** | Per-line SRT/JSON generation with timing | Built-in (no forced alignment needed — see §6) |
| **UI** | Upload, casting editor, playback, corner mode | Gradio 5.x |
| **Cache** | Content-addressed TTS chunk cache | SHA256 hashing, filesystem |
| **Export** | Zip/download of all artifacts | `zipfile`, Gradio file components |

### Directory Structure (project)

```
scriptstage/
├── app.py                    # Gradio app entry point
├── core/
│   ├── models.py             # Pydantic data models
│   ├── parser/
│   │   ├── __init__.py       # dispatch by extension
│   │   ├── fdx.py            # Final Draft XML
│   │   ├── docx_parser.py    # DOCX with styles
│   │   ├── pdf_parser.py     # PDF with position heuristics
│   │   └── txt_parser.py     # Fountain-like plain text
│   ├── caster/
│   │   ├── __init__.py
│   │   ├── characters.py     # extraction, dedup, alias resolution
│   │   ├── voice_inventory.py# voice library definition
│   │   ├── scoring.py        # prominence scoring algorithm
│   │   └── assigner.py       # constraint-based voice assignment
│   ├── synth/
│   │   ├── __init__.py
│   │   ├── engine.py         # qwen3-tts wrapper
│   │   ├── chunker.py        # script → TTS segments
│   │   ├── assembler.py      # chunks → full audio
│   │   └── cache.py          # content-addressed cache
│   └── captions/
│       ├── __init__.py
│       ├── srt.py            # SRT writer
│       └── json_caps.py      # JSON caption writer
├── ui/
│   ├── __init__.py
│   ├── upload_tab.py
│   ├── casting_tab.py
│   ├── playback_tab.py
│   └── corner.py             # corner overlay mode
├── voices/                   # voice profile presets + augmented profiles
│   └── profiles.json
├── runs/                     # generated output per project
└── tests/
```

---

## 2. Tech Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| **Language** | Python 3.12 | Matches `qwen3-tts` conda env |
| **Conda env** | `qwen3-tts` (existing) | Already has torch, transformers, qwen-tts, flash-attn |
| **TTS Engine** | `qwen-tts` package → `Qwen3TTSModel` | Local, GPU-accelerated, 9 discrete speakers + VoiceDesign |
| **TTS Models** | 1.7B-CustomVoice (primary) + 1.7B-VoiceDesign (augmentation) | All weights already downloaded locally at `~/models/` |
| **UI** | Gradio 5.x | Fast to build, supports custom JS/CSS for corner mode |
| **Data models** | Pydantic v2 | Validation, serialization, type safety |
| **PDF parsing** | PyMuPDF (`fitz`) | Already available; gives text + bbox positions |
| **FDX parsing** | `lxml` | FDX is XML; lxml is the standard |
| **DOCX parsing** | `python-docx` | Standard; reads paragraph styles |
| **Audio** | `soundfile` + `pydub` + `ffmpeg` | Read/write wav, concat, speed adjust, mp3 export |
| **Caching** | SHA256 content hash → filesystem | Simple, reliable, no DB needed |

### Packages to Install (into qwen3-tts env)

```bash
pip install gradio python-docx lxml pydub pydantic soundfile
# PyMuPDF (fitz) — check if installed, else: pip install PyMuPDF
# ffmpeg — system package, likely already present
```

---

## 3. Qwen3-TTS Voice Capabilities — Investigation Results

### What's Installed

- **Conda env**: `qwen3-tts` (Python 3.12) with `qwen-tts` package ✅
- **Models on disk** (all at `~/models/`):
  - `Qwen3-TTS-12Hz-1.7B-CustomVoice` — **9 named speakers**, instruction-controllable
  - `Qwen3-TTS-12Hz-1.7B-VoiceDesign` — **generates arbitrary voices from text descriptions**
  - `Qwen3-TTS-12Hz-1.7B-Base` — **3-second voice clone from audio reference**
  - `Qwen3-TTS-12Hz-0.6B-CustomVoice` — smaller, same 9 speakers (fallback)
  - `Qwen3-TTS-12Hz-0.6B-Base` — smaller clone model (fallback)
  - `Qwen3-TTS-Tokenizer-12Hz` — shared speech tokenizer

### The 9 Built-In Speakers (CustomVoice model)

Retrieved from `config.talker_config.spk_id`:

| Speaker ID | Inferred Profile |
|-----------|-----------------|
| `serena` | Female |
| `vivian` | Female |
| `uncle_fu` | Male, older |
| `ryan` | Male |
| `aiden` | Male |
| `ono_anna` | Female (Japanese name, likely accented) |
| `sohee` | Female (Korean name) |
| `eric` | Male |
| `dylan` | Male |

**Gender split**: ~5 male, ~4 female. Each speaker also accepts an `instruct` parameter for emotional/stylistic control ("speak angrily", "whisper", "speak slowly and sadly").

### Voice Differentiation Strategy — **This is Case 1 + Case 2 combined**

The spec asked us to detect which of 3 cases applies. **Answer: primarily Case 1** (discrete speakers) but **massively augmented** by two additional systems:

#### Tier 1: 9 Native Speakers (CustomVoice) — Zero latency overhead
- Use `generate_custom_voice(text, speaker="dylan", language="English", instruct="...")`
- Each speaker is perceptually distinct — different timbre baked into model weights
- The `instruct` parameter provides **per-line emotional control** (we can pass parenthetical cues!)
- These are the primary voices for lead roles

#### Tier 2: VoiceDesign-Generated Voices — For casts > 9 characters
- Use `generate_voice_design(text, instruct="A warm elderly British woman with a gentle, raspy voice")`
- Creates novel voices from **text descriptions alone** — no reference audio needed
- We pre-generate a library of ~20 designed voice profiles at startup
- Slightly more compute per generation, but voice is consistent per description string
- **Key insight**: same description + same text = same voice characteristics (deterministic via seed)

#### Tier 3: Voice Clone (Base model) — Optional advanced feature
- Use `generate_voice_clone()` with 3-second reference audio
- Users could upload reference clips for specific characters
- Defer to Phase 2; not needed for core functionality

#### Effective Voice Palette: **29+ distinct voices**

| Source | Count | Best For |
|--------|-------|----------|
| Native speakers | 9 | Lead roles (fastest, most reliable) |
| Native + instruct variations | 9 × ~3 styles = ~27 | Same speaker, different emotion |
| VoiceDesign presets | 20+ pre-designed | Supporting roles, distinct extras |
| Voice clone | Unlimited | User-provided reference (Phase 2) |

For "The Unfinished Swan" (estimated ~15-20 speaking roles), 9 native speakers covers leads comfortably. VoiceDesign handles the rest.

### Narrator Strategy

- **Default narrator**: `eric` with instruct "Speak in a calm, neutral, measured narration voice"
- Action lines: same narrator, instruct "Read quickly and matter-of-factly"
- Sluglines: same narrator, instruct "Announce clearly and briefly"
- Configurable — user can pick any speaker or VoiceDesign profile

---

## 4. File Parsing Strategy

### 4A. PDF Parsing (validated against "The Unfinished Swan")

**Key discovery**: PyMuPDF extracts text with bbox positions. The test PDF uses `CourierFinalDraft` font at 12pt with **perfectly consistent x-offsets** that map directly to screenplay element types:

| x-offset (approx) | Element Type | Example |
|-------------------|-------------|---------|
| ~108 | Action / Scene description | "He swipes the OPEN BOTTLE..." |
| ~180 | Dialogue | "THANK YOU for remembering!" |
| ~209 | Parenthetical | "(beat, then)" |
| ~252 | Character cue | "MONROE (CONT'D)" |
| ~108 + **Bold** | Slug line / transition | "PHOTO OF THE CANALS" |

**Algorithm**:
1. Extract all text spans with `page.get_text('dict')` → get bbox + font info per span
2. Classify each line by x-offset into bins (with ±10px tolerance):
   - `x ≈ 252`: CHARACTER CUE → extract name, strip extensions
   - `x ≈ 180`: DIALOGUE → attach to preceding character cue
   - `x ≈ 209`: PARENTHETICAL → attach to preceding character cue
   - `x ≈ 108 + bold font`: SLUG LINE → new scene
   - `x ≈ 108 + regular`: ACTION
3. **Adaptive calibration**: on first pass, histogram all x-offsets → detect the 4-5 clusters automatically. This handles PDFs with different margins.
4. Page numbers (typically top-right, first line) → strip
5. Scene numbering: increment on each slug line; extract scene numbers if present
6. **Scanned PDF detection**: if `page.get_text()` returns <10 chars per page on average → flag as image-based, show warning

**Edge cases from the test script**:
- Bold text inline within action (e.g., "STAY ON NOLAN") — bold mid-action is emphasis, not a slug. Only classify as slug if bold text starts at line beginning AND matches INT./EXT./PHOTO/FLASHBACK patterns, or is ALL CAPS + appears at action indent.
- Character introductions inline (e.g., "**FRED** (50s), frozen mid-struggle") — bold name at high x-offset within action. Detect as character introduction, add to character list but don't create a dialogue cue.
- Multi-page dialogue: "(MORE)" / "(CONT'D)" markers → continuation of previous character's dialogue.
- Title page (page 1): detect by absence of screenplay formatting or presence of "Written by" → extract title, skip from element list.

### 4B. FDX Parsing (Final Draft XML)

Highest-fidelity parse. FDX structure:
```xml
<FinalDraft>
  <Content>
    <Paragraph Type="Scene Heading">
      <Text>EXT. LAKE TOWN - DAY</Text>
    </Paragraph>
    <Paragraph Type="Action">...</Paragraph>
    <Paragraph Type="Character">MONROE</Paragraph>
    <Paragraph Type="Parenthetical">(whispers)</Paragraph>
    <Paragraph Type="Dialogue">Thanks, Fred!</Paragraph>
  </Content>
</FinalDraft>
```

**Algorithm**:
1. Parse XML with `lxml.etree`
2. Map `Paragraph/@Type` directly to element types:
   - "Scene Heading" → slug
   - "Action" → action
   - "Character" → character cue
   - "Parenthetical" → parenthetical
   - "Dialogue" → dialogue
   - "Transition" → transition (FADE IN, CUT TO, etc.)
3. Handle `<DualDialogue>` containers (simultaneous dialogue) → serialize as sequential
4. Extract `ScriptNotes`, `HeaderAndFooter` for metadata
5. This is basically a direct mapping — minimal heuristics needed

### 4C. DOCX Parsing

**Algorithm**:
1. Load with `python-docx`
2. First attempt: check paragraph styles (`paragraph.style.name`):
   - "Scene Heading", "Character", "Dialogue", "Parenthetical", "Action" — if present, direct mapping (Final Draft-exported DOCX often has these)
3. Fallback to heuristic mode (same as TXT but with formatting hints):
   - Bold + ALL CAPS at margin → slug line
   - ALL CAPS centered → character cue
   - Indented following character → dialogue
   - Italic in parentheses → parenthetical
4. Use paragraph indentation (`paragraph.paragraph_format.left_indent`) as secondary signal

### 4D. TXT / Fountain Parsing

Follow Fountain markup spec (https://fountain.io/syntax) plus general heuristics:

1. **Fountain markers** (if present):
   - Lines starting with `.` → forced slug
   - Lines starting with `@` → forced character
   - `INT.` / `EXT.` → slug
   - ALL CAPS line followed by non-blank line → character + dialogue
   - Lines in `()` after character → parenthetical
   - `>` centered text → transition
2. **Plain text heuristics** (no Fountain markers):
   - Blank-line delimited blocks
   - ALL CAPS line alone → likely character cue (validate: followed by non-caps text)
   - INT./EXT. prefix → slug
   - Everything else → action
3. This is the least reliable; show confidence indicator in UI

### Shared Post-Processing (all formats)

After raw parse:
1. **Title extraction**: first slug or title page content → `meta.title`
2. **Page count**: for PDF = page count; others = estimate from element count (~55 elements/page)
3. **Scene numbering**: sequential, reset on each slug
4. **Element ID assignment**: `e1`, `e2`, ... sequential
5. **Validation pass**: orphaned dialogue (no preceding character cue) → attach to NARRATOR

---

## 5. Casting Algorithm Design — The Scoring & Assignment Pipeline

This is the heart of ScriptStage. Three phases: **Extract → Score → Assign**.

### Phase 1: Character Extraction & Normalization

```
Raw character cues from parser
        │
        ▼
┌─────────────────────────┐
│   Normalize & Deduplicate│
│                         │
│  "MONROE (CONT'D)" ──► MONROE
│  "MONROE (V.O.)"   ──► MONROE
│  "MONROE (O.S.)"   ──► MONROE
│  "YOUNG MONROE"     ──► YOUNG MONROE (distinct)
│  "DR. PATEL"        ──► DR. PATEL
│  "GILLY"            ──► GILLY
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│    Build Character Table │
│                         │
│  For each unique name:  │
│  - Count dialogue lines │
│  - Count total words    │
│  - List scenes present  │
│  - Track first/last     │
│    scene appearance     │
│  - Detect gender hints  │
│    from pronouns in     │
│    surrounding action   │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│   Alias Suggestion       │
│                         │
│  Auto-detect candidates:│
│  - Levenshtein < 3      │
│  - Prefix match (YOUNG X│
│    → X, OLD X → X)     │
│  - Present to user for  │
│    merge confirmation   │
└─────────────────────────┘
```

**Normalization rules** (applied in order):
1. Strip trailing extensions: `(CONT'D)`, `(V.O.)`, `(O.S.)`, `(O.C.)`, `(PRE-LAP)`, `(CONT'D; V.O.)`
2. Strip leading/trailing whitespace and punctuation
3. Collapse multiple spaces
4. Preserve age/qualifier prefixes as distinct: YOUNG X, OLD X, LITTLE X, DR. X, etc.
5. Case-normalize to UPPER for matching, preserve original for display

**Gender inference** (best-effort, for voice assignment hints):
- Scan action lines within ±3 elements of character's dialogue for pronouns: he/him/his → male, she/her/hers → female
- Character names with common gendered names (database of ~500 names) → hint
- Inline character introductions: "**GILLY** (20s, sharp-eyed)" → extract age and any gender words
- Store as `gender_hint: "male" | "female" | "unknown"` — never hard-code, always overridable

### Phase 2: Prominence Scoring

Each character gets a **prominence score** (0.0–1.0, normalized so the lead = 1.0).

```python
def compute_prominence(char, total_dialogue_words, total_scenes):
    # Raw metrics
    word_share = char.total_words / total_dialogue_words  # 0–1
    line_share = char.total_lines / max_lines_any_char    # 0–1
    scene_share = len(char.scenes) / total_scenes          # 0–1
    
    # Structural metrics
    arc_spread = (char.last_scene - char.first_scene) / total_scenes  # 0–1
    act_presence = count_acts_present(char, total_scenes) / 3  # 0–1 (3 acts)
    
    # Dialog density: avg words per line (higher = more substantive dialogue)
    density = min(char.total_words / max(char.total_lines, 1) / 20, 1.0)
    
    # Weighted composite
    raw = (
        0.35 * word_share +      # Words are the strongest signal
        0.20 * line_share +      # Line count matters
        0.20 * scene_share +     # Scene presence
        0.15 * arc_spread +      # Characters spanning the whole script
        0.05 * act_presence +    # Present in all three acts
        0.05 * density           # Substantive dialogue
    )
    
    return raw  # Normalized to 0–1 after computing all characters
```

**Act estimation** (no explicit act markers in most scripts):
- Act 1: scenes 1–25% 
- Act 2: scenes 25%–75%
- Act 3: scenes 75%–100%

**Output**: sorted list of characters with prominence scores. Example for "The Unfinished Swan":
```
MONROE:       1.00  (lead — appears in nearly every scene)
GILLY:        0.65  (major supporting)
KING:         0.40  (significant role)
...
FRED:         0.05  (bit part, 2 lines)
```

### Phase 3: Voice Assignment (Constraint-Based)

This is a **constraint satisfaction + optimization** problem, not a random assignment.

#### Voice Inventory Definition

```python
# voices/profiles.json structure
{
  "native_speakers": [
    {"id": "dylan",    "gender": "male",   "age": "young_adult", "quality": "warm_casual",    "tier": 1},
    {"id": "ryan",     "gender": "male",   "age": "adult",       "quality": "clear_neutral",  "tier": 1},
    {"id": "eric",     "gender": "male",   "age": "adult",       "quality": "deep_steady",    "tier": 1},
    {"id": "aiden",    "gender": "male",   "age": "young_adult", "quality": "bright_energetic","tier": 1},
    {"id": "uncle_fu", "gender": "male",   "age": "older",       "quality": "warm_gravelly",  "tier": 1},
    {"id": "vivian",   "gender": "female", "age": "young_adult", "quality": "clear_bright",   "tier": 1},
    {"id": "serena",   "gender": "female", "age": "adult",       "quality": "warm_smooth",    "tier": 1},
    {"id": "ono_anna", "gender": "female", "age": "young_adult", "quality": "soft_gentle",    "tier": 1},
    {"id": "sohee",    "gender": "female", "age": "young_adult", "quality": "crisp_clear",    "tier": 1}
  ],
  "voice_design_presets": [
    {"id": "vd_male_teen",       "description": "A teenage boy with a slightly cracking, enthusiastic voice", "tier": 2},
    {"id": "vd_male_gruff",      "description": "A gruff middle-aged man with a deep, gravelly voice",        "tier": 2},
    {"id": "vd_male_elderly",    "description": "An elderly gentleman with a thin, wavering but kind voice",  "tier": 2},
    {"id": "vd_female_elderly",  "description": "An elderly woman with a warm, slightly trembling voice",     "tier": 2},
    {"id": "vd_female_tough",    "description": "A tough, no-nonsense woman with a sharp, clipped delivery",  "tier": 2},
    {"id": "vd_male_pompous",    "description": "A pompous, self-important man with precise enunciation",     "tier": 2},
    {"id": "vd_child_boy",       "description": "A young boy around 8 years old, bright and curious",         "tier": 2},
    {"id": "vd_child_girl",      "description": "A young girl around 8 years old, sweet and energetic",       "tier": 2},
    {"id": "vd_male_whisper",    "description": "A mysterious man speaking in a hushed, breathy whisper",     "tier": 2},
    {"id": "vd_female_breathy",  "description": "A soft-spoken woman with a dreamy, breathy quality",         "tier": 2},
    // ... ~10 more presets covering various archetypes
  ],
  "narrator_default": {
    "id": "eric",
    "instruct": "Speak in a calm, neutral, measured narration voice"
  }
}
```

#### Assignment Algorithm

```
Input: characters (sorted by prominence), voice_inventory, script_scenes
Output: casting.json

1. PARTITION characters into tiers:
   - LEADS:    prominence ≥ 0.50  (get unique Tier 1 native voices)
   - SUPPORT:  0.15 ≤ prominence < 0.50  (get unique Tier 1 or Tier 2 voices)
   - MINOR:    prominence < 0.15  (may share from a pool)

2. GENDER-FILTER voices for each character:
   - If gender_hint == "male"   → only male voices
   - If gender_hint == "female" → only female voices
   - If "unknown"               → all voices eligible

3. ASSIGN LEADS (greedy, highest prominence first):
   For each lead character (descending prominence):
     a. Filter eligible voices (gender match, not yet assigned)
     b. Score each eligible voice:
        - quality_fit: subjective match of voice quality to character age/type
        - exclusivity_bonus: +0.3 if Tier 1 native voice (more distinct)
        - scene_collision_penalty: for each already-assigned character
          sharing ≥3 scenes with this character AND having a "similar" voice
          (same gender + same age bracket), apply -0.2
     c. Assign highest-scoring voice
     d. Mark voice as used

4. ASSIGN SUPPORT (same algorithm, but Tier 2 voices now eligible):
   - Same scoring but lower exclusivity requirement
   - Scene collision check against all previously assigned characters

5. ASSIGN MINOR roles:
   - Characters with < N lines (configurable, default 5) → "VARIOUS" pool
   - Pool uses 3 rotating voices (2 male, 1 female or vice versa)
   - Within a single scene, no two minor characters share a voice
   - User can override to give any minor character a dedicated voice

6. NARRATOR assignment:
   - Default: `eric` with narration instruct
   - Constraint: narrator voice MUST differ from all lead voices
   - If `eric` is assigned to a lead, fall back to next eligible male voice
```

#### Scene Collision Matrix

Pre-compute a matrix of character co-occurrence:

```
          MONROE  GILLY  KING  NOLAN  ...
MONROE      -      28     12    8
GILLY      28       -      6    3
KING       12       6      -    2
NOLAN       8       3      2    -
```

Characters with high co-occurrence (sharing many scenes) MUST have maximally distinct voices. This is the primary constraint beyond gender matching.

#### Voice Similarity Estimation

Since we don't have pre-computed speaker embeddings for similarity, use heuristic similarity:
- Same gender + same age bracket = HIGH similarity → avoid pairing in co-occurring roles
- Same gender + different age = MEDIUM similarity → acceptable if necessary
- Different gender = LOW similarity → always fine

For VoiceDesign voices, the text description itself encodes distinctiveness — we design them to be maximally spread across the attribute space.

### Casting Output Example (for "The Unfinished Swan")

```json
{
  "narrator": {
    "voice_id": "eric",
    "voice_type": "native",
    "instruct": "Speak in a calm, neutral, measured narration voice",
    "label": "Narrator (Eric)"
  },
  "roles": {
    "MONROE": {
      "voice_id": "dylan",
      "voice_type": "native",
      "instruct_default": "",
      "label": "Dylan (Young Male, warm casual)",
      "prominence": 1.00,
      "gender_hint": "male",
      "total_lines": 180,
      "total_words": 9500,
      "scenes": 85
    },
    "GILLY": {
      "voice_id": "vivian",
      "voice_type": "native",
      "instruct_default": "",
      "label": "Vivian (Young Female, clear bright)",
      "prominence": 0.65,
      "gender_hint": "female",
      "total_lines": 95,
      "total_words": 4800,
      "scenes": 42
    },
    "KING": {
      "voice_id": "uncle_fu",
      "voice_type": "native",
      "instruct_default": "",
      "label": "Uncle Fu (Older Male, warm gravelly)",
      "prominence": 0.40,
      "gender_hint": "male",
      "total_lines": 50,
      "total_words": 2200,
      "scenes": 18
    }
  },
  "shared_pool": {
    "voices": ["vd_male_gruff", "vd_female_tough", "vd_male_elderly"],
    "assignments": {
      "FRED": "vd_male_gruff",
      "JOGGER": "vd_male_elderly"
    }
  }
}
```

### Manual Override UI

- **Per-character dropdown**: shows all available voices, current assignment highlighted
- **Preview button**: generates 8–12 seconds of a representative line (longest dialogue line for that character, or a manually selected one)
- **Merge button**: "Merge YOUNG MONROE → MONROE" — combines stats, reassigns all dialogue
- **"Group as VARIOUS" checkbox**: for minor characters, assign to shared pool
- **Narrator picker**: same dropdown as characters
- **"Re-cast All" button**: re-runs the assignment algorithm (e.g., after merges)
- **"Lock" toggle per character**: locked assignments survive re-cast

---

## 6. Audio Pipeline: Chunked Synthesis → Assembly → SRT

### 6A. Script → TTS Segment Plan

Convert the parsed script elements into an ordered list of **TTS jobs**:

```python
@dataclass
class TTSJob:
    job_id: str                    # "j0001"
    element_ids: list[str]         # which script elements this covers
    text: str                      # the text to synthesize
    voice_id: str                  # speaker or VoiceDesign ID
    voice_type: str                # "native" | "voice_design" | "narrator"
    instruct: str                  # emotional/style instruction
    scene: int                     # scene number
    element_type: str              # "dialogue" | "action" | "slug" | "parenthetical"
    character: Optional[str]       # character name (None for narrator lines)
```

**Segmenting rules**:
- Each **dialogue line** (continuous dialogue for one character before next cue) = 1 TTS job
- Each **action paragraph** = 1 TTS job (narrator voice)
- Each **slug line** = 1 TTS job (narrator, quick delivery)
- Each **parenthetical** = either:
  - Folded into the dialogue job as prefix: `"(whispers) Thanks, Fred!"` — preferred, more natural
  - OR separate narrator job if it's a long performance direction
- **Max text length per job**: ~500 characters. If action paragraph exceeds this, split at sentence boundaries.

**Instruct mapping from parentheticals**:
```python
PARENTHETICAL_TO_INSTRUCT = {
    "whispers": "Speak in a quiet whisper",
    "shouting": "Speak loudly and forcefully", 
    "beat": None,  # just a pause marker, insert silence
    "sotto": "Speak quietly, under the breath",
    "angry": "Speak with anger and frustration",
    "excited": "Speak with excitement and energy",
    "sarcastic": "Speak with dry sarcasm",
    # ... extensible mapping
}
```

For parentheticals not in the map, pass them verbatim as instruct (qwen3-tts handles natural language instructions).

### 6B. Synthesis Execution

```
TTS Jobs Queue
     │
     ▼
┌──────────────────────┐
│   Cache Check         │
│   hash(text + voice   │
│   + instruct + speed) │
│   → hit? return cached│
└──────┬───────────────┘
       │ miss
       ▼
┌──────────────────────┐
│   qwen3-tts Generate  │
│                       │
│   Native voices:      │
│   model.generate_     │
│   custom_voice(       │
│     text, speaker,    │
│     language, instruct│
│   )                   │
│                       │
│   VoiceDesign voices: │
│   model.generate_     │
│   voice_design(       │
│     text, instruct=   │
│     voice_description │
│   )                   │
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│   Post-process        │
│   - Trim silence      │
│   - Normalize volume  │
│   - Save chunk .wav   │
│   - Record duration   │
│   - Update cache      │
└──────────────────────┘
```

**Model loading strategy**:
- Load 1.7B-CustomVoice at startup (covers all native speakers) — ~3.4GB VRAM in bf16
- Load 1.7B-VoiceDesign **only if needed** (cast has VoiceDesign voices) — swap or co-load
- RTX 5090 has 24GB VRAM; both models together ~7GB, fits easily
- Use `flash_attention_2` for memory efficiency

**Batch processing**:
- Process jobs sequentially (TTS is autoregressive, batching has limited benefit for varied-length inputs)
- BUT: can batch multiple short lines for the same speaker in one call
- Target: ~2-4 seconds of generation time per ~10 seconds of audio (RTX 5090 should be fast)

**Streaming start** (30-90 second target):
- Begin playback after first scene's chunks are generated (~10-20 TTS jobs)
- Continue generating remaining scenes in background
- UI shows progress bar: "Generating scene 5/42..."

### 6C. Assembly

```python
def assemble_full_audio(chunks: list[ChunkResult], output_dir: Path):
    # 1. Concatenate all chunk WAVs in order
    #    Insert configurable silence between elements:
    #    - Between scenes: 1.5s silence
    #    - Between action→dialogue: 0.3s
    #    - Between dialogue→dialogue (different char): 0.5s  
    #    - Between dialogue→dialogue (same char, cont'd): 0.2s
    #    - "(beat)" parenthetical: 0.8s silence, no audio
    
    # 2. Write chunks/0001.wav, chunks/0002.wav, ...
    # 3. Write table_read_full.wav (concatenated)
    # 4. Optionally encode to MP3 via ffmpeg
    
    # 5. Compute cumulative timestamps for each chunk
    #    → feeds into caption generation
```

### 6D. Caption Generation

**Strategy: one TTS job = one caption entry** (exact alignment, no guessing).

Since each dialogue line / action paragraph is synthesized individually, we know the **exact duration** of each chunk from the WAV file metadata. Captions are trivially accurate:

```python
def generate_captions(chunks: list[ChunkResult]) -> tuple[str, dict]:
    srt_entries = []
    json_entries = []
    current_ms = 0
    
    for i, chunk in enumerate(chunks):
        start_ms = current_ms
        end_ms = current_ms + chunk.duration_ms + chunk.trailing_silence_ms
        
        speaker_label = chunk.character or "NARRATOR"
        
        srt_entries.append(SRTEntry(
            index=i+1,
            start=start_ms,
            end=start_ms + chunk.duration_ms,  # exclude trailing silence
            text=f"[{speaker_label}] {chunk.text}"
        ))
        
        json_entries.append({
            "id": chunk.job_id,
            "start_ms": start_ms,
            "end_ms": start_ms + chunk.duration_ms,
            "text": chunk.text,
            "speaker": speaker_label,
            "element_ids": chunk.element_ids,
            "scene": chunk.scene,
            "type": chunk.element_type
        })
        
        current_ms = end_ms
    
    return format_srt(srt_entries), {"captions": json_entries}
```

**SRT format**:
```
1
00:00:00,000 --> 00:00:03,200
[NARRATOR] EXT. LAKE TOWN - DAY

2
00:00:03,500 --> 00:00:12,800
[NARRATOR] Striking and high contrast, it depicts a small, deep-south lake town...

3
00:00:13,300 --> 00:00:15,100
[MONROE] THANK YOU for remembering!
```

---

## 7. UI Design

### Framework: Gradio 5.x

Gradio is the right call: fast to build, supports custom CSS/JS, already in the Python ecosystem, and Qwen's own examples use it.

### Layout: Three Tabs + Corner Mode

#### Tab 1: Upload & Parse

```
┌─────────────────────────────────────────────┐
│  📁 Upload Script                           │
│  [Drop FDX/DOCX/PDF/TXT here]              │
│                                             │
│  ── Parsed Result ──────────────────────    │
│  Title: THE UNFINISHED SWAN                 │
│  Pages: ~110  |  Scenes: 87  |  Format: PDF │
│                                             │
│  Characters Found: 18                       │
│  ┌──────────────────────────────────────┐   │
│  │ # │ Character    │ Lines │ Words │ Sc│   │
│  │ 1 │ MONROE       │  180  │ 9500  │ 85│   │
│  │ 2 │ GILLY        │   95  │ 4800  │ 42│   │
│  │ 3 │ KING         │   50  │ 2200  │ 18│   │
│  │ ...                                  │   │
│  └──────────────────────────────────────┘   │
│                                             │
│  ⚠ Alias suggestions:                      │
│  "YOUNG MONROE" → merge into "MONROE"? [✓] │
│                                             │
│  [Continue to Casting →]                    │
└─────────────────────────────────────────────┘
```

#### Tab 2: Casting

```
┌─────────────────────────────────────────────┐
│  🎭 Voice Casting                           │
│                                             │
│  Narrator: [Eric ▾] "Calm narration"        │
│            [🔊 Preview]                     │
│                                             │
│  ── Lead Roles ─────────────────────────    │
│  MONROE (prom: 1.00, 180 lines)            │
│  Voice: [Dylan ▾]  Instruct: [default ▾]   │
│  [🔊 Preview] [🔒 Lock]                    │
│                                             │
│  GILLY (prom: 0.65, 95 lines)              │
│  Voice: [Vivian ▾]  Instruct: [default ▾]  │
│  [🔊 Preview] [🔒 Lock]                    │
│                                             │
│  ── Supporting ──────────────────────────   │
│  KING (prom: 0.40, 50 lines)               │
│  Voice: [Uncle Fu ▾]  [🔊 Preview]         │
│                                             │
│  ── Minor (shared pool) ────────────────    │
│  ☐ FRED (2 lines) → pool voice             │
│  ☐ JOGGER (1 line) → pool voice            │
│  [Give dedicated voice] [Group as VARIOUS]  │
│                                             │
│  [⟳ Re-cast All] [Generate Table Read →]   │
└─────────────────────────────────────────────┘
```

#### Tab 3: Playback

```
┌─────────────────────────────────────────────┐
│  ▶ Table Read Player                        │
│                                             │
│  [▶ ⏸] ───●─────────────── 12:34 / 1:42:30│
│  Speed: [1.25x ▾]  Scene: [Jump to... ▾]   │
│                                             │
│  ── Captions ───────────────────────────    │
│                                             │
│     [NARRATOR] EXT. LAKE TOWN - DAY         │
│                                             │
│  ►  [MONROE] THANK YOU for remembering!     │
│     I'm 18. Or was it 19?... Crap.          │
│                                             │
│     [MONROE] What I do know is I'm old      │
│     enough for one of these--               │
│                                             │
│  Progress: Generating scene 15/87... ██░░   │
│                                             │
│  [📥 Download All] [🪟 Corner Mode]         │
└─────────────────────────────────────────────┘
```

#### Corner Overlay Mode

Activated via button or `?corner=1` URL parameter. Uses Gradio's custom CSS + JS:

```
                                    ┌──────────────┐
                                    │ ▶ ⏸  1.25x   │
                                    │──────────────│
                                    │ [MONROE]     │
                                    │ THANK YOU for│
                                    │ remembering! │
                                    │              │
                                    │ ◄ Scene  ►   │
                                    └──────────────┘
                                    ↕ resizable, draggable
```

Implementation:
- Gradio `gr.HTML` block with custom JS for position: fixed, bottom-right
- Receives caption updates via Gradio streaming/polling
- Minimal chrome: speaker name, current line, transport controls
- Keyboard shortcuts: Space=play/pause, ←→=±5s, ↑↓=±scene

### Playback Rate

- Default 1.25x set via HTML5 `<audio>` `playbackRate`
- Slider: 0.75x to 2.0x in 0.05 increments
- Captions must sync to adjusted rate (JS-side: caption timings adjusted by `1/playbackRate`)

---

## 8. Caching Strategy

### Content-Addressed Cache

```
runs/<project>/cache/
  <sha256>.wav          # cached audio chunk
  <sha256>.meta.json    # metadata: text, voice, instruct, duration
  manifest.json         # maps job_id → cache hash
```

**Cache key computation**:
```python
def cache_key(text: str, voice_id: str, voice_type: str, instruct: str) -> str:
    content = f"{text}|{voice_id}|{voice_type}|{instruct}"
    return hashlib.sha256(content.encode()).hexdigest()
```

**Invalidation**: when user changes a voice assignment for a character, only that character's TTS jobs are re-keyed. All other characters' cached chunks remain valid.

**Selective regeneration flow**:
1. User changes GILLY's voice from `vivian` → `serena`
2. System identifies all TTS jobs where `character == "GILLY"`
3. Re-compute cache keys with new voice
4. Cache miss → regenerate only GILLY's lines
5. Re-assemble full audio with new chunks spliced in
6. Regenerate captions (timings may change)

---

## 9. Estimated Phases & Effort

### Phase 1: Core Pipeline (MVP) — ~3-4 days ✅ COMPLETE (2026-03-05)
- [x] Project scaffolding, Pydantic models
- [x] PDF parser (position-based, validated against test script)
- [x] TXT parser (Fountain heuristics)
- [x] Character extraction + normalization
- [x] Basic casting: prominence scoring + greedy assignment
- [x] TTS engine wrapper (CustomVoice only, 9 speakers + fallback silent placeholders)
- [x] Sequential synthesis → chunk WAVs → full assembly
- [x] SRT + JSON caption generation
- [x] Minimal Gradio UI: upload → parse → generate → play

### Phase 2: Full Casting System — ~2-3 days
- [ ] Scene collision matrix + constraint-based assignment
- [ ] VoiceDesign integration (Tier 2 voices for large casts)
- [ ] Gender inference from script context
- [ ] Voice preview (per-character sample generation)
- [ ] Casting editor UI: dropdowns, lock, merge, re-cast
- [ ] Alias suggestion + merge flow
- [ ] Minor role pooling / VARIOUS grouping

### Phase 3: Playback & Polish — ~2 days
- [ ] Streaming playback (start before full generation)
- [ ] Corner overlay mode (custom CSS/JS)
- [ ] Caption sync with variable playback rate
- [ ] Scene navigation (jump, prev/next)
- [ ] Keyboard shortcuts
- [ ] Speed slider

### Phase 4: Caching & Export — ~1 day
- [ ] Content-addressed TTS cache
- [ ] Selective regeneration on voice change
- [ ] Export: download links for all artifacts
- [ ] Project runs directory structure
- [ ] MP3 encoding option

### Phase 5: Remaining Parsers + Hardening — ~1-2 days
- [ ] FDX parser
- [ ] DOCX parser
- [ ] Scanned PDF detection + warning
- [ ] Edge case handling (dual dialogue, orphaned lines, etc.)
- [ ] Error handling, progress reporting, logging

### Total Estimated Effort: ~9-12 days

### Hardware Utilization Notes

- **RTX 5090** (24GB VRAM): 1.7B model in bf16 ≈ 3.4GB. Room for both CustomVoice + VoiceDesign simultaneously.
- **27GB RAM**: sufficient for PyMuPDF + model overhead
- **Synthesis speed estimate**: 1.7B model on RTX 5090 should produce ~30-50x realtime (conservative). A 110-page script ≈ ~90 minutes of audio → ~2-3 minutes generation time.
- **Streaming start**: first scene (~1 min audio) should be ready in <30 seconds.

---

## Appendix: Key Decisions & Rationale

| Decision | Choice | Why |
|----------|--------|-----|
| One TTS job per caption line | Yes | Eliminates alignment guessing entirely |
| CustomVoice as primary | Yes | 9 native voices are faster and more reliable than VoiceDesign |
| VoiceDesign for overflow | Yes | Unlimited voice diversity for large casts without audio references |
| PDF parsing by x-offset | Yes | Validated against real screenplay PDF — positions are perfectly consistent |
| Gradio over Streamlit | Yes | Better audio/media support, custom JS/CSS, familiar ecosystem |
| Sequential over batch TTS | Yes | Varied text lengths + different speakers = poor batch efficiency |
| Pydantic models | Yes | Type safety, easy JSON serialization for all artifacts |
| Parenthetical → instruct | Yes | Qwen3-TTS natively handles natural language emotion instructions |
