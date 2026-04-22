# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ScriptStage** converts screenplays (PDF, FDX, DOCX, TXT) into full-cast AI table reads with automatic character casting, voice synthesis, and synchronized captions. It uses Qwen3-TTS (1.7B) models served remotely over HTTP.

## Running & Development

**Required conda environment:** `qwen3-tts`

```bash
source /home/bear/miniconda3/bin/activate qwen3-tts
python app.py   # Gradio UI on port 7870
```

**TTS server** (runs on separate GPU machine, e.g. WSL/RTX 5090):
```bash
python scripts/tts_server.py   # FastAPI on port 8000
```

Configure the client with:
```bash
export TTS_SERVER_URL=http://<tailscale-ip>:8000
```

**End-to-end tests:**
```bash
python e2e_test_final.py        # Full parse → cast → synth → verify pipeline
python e2e_stages_6_8.py        # Stages 6–8 (synth + assembly + captions)
python validate_audio.py        # Audio output validation
```

No build step, no linter config, no package manager — dependencies live in the conda environment.

## Architecture

The pipeline flows through five stages, each in its own `core/` subpackage:

```
Upload → core/parser/ → core/caster/ → core/synth/ → core/captions/ → Gradio playback
```

All inter-stage data is represented as Pydantic v2 models in `core/models.py`:
- `Script` → parsed screenplay with `ScriptElement` list and `Character` registry
- `CastingResult` → narrator + per-character voice assignments
- `TTSJob` → synthesis job (text, voice_type, speaker, instruct)
- `ChunkResult` → completed audio chunk with duration and timing metadata
- `CaptionEntry` → timestamped subtitle line with speaker

**Run output** is written to `runs/<timestamp>_<scriptname>/` containing `parsed_script.json`, `casting.json`, `chunks/*.wav`, `table_read_full.wav`, and caption files.

### core/parser/

`pdf_parser.py` is the only implemented parser. It uses PyMuPDF (`fitz`) with bounding-box x-offset clustering to detect screenplay formatting (sluglines are left-aligned, dialogue is indented ~200px). FDX, DOCX, and TXT parsers raise `NotImplementedError`.

### core/caster/

Character casting is multi-step:

1. **`characters.py`** — Extracts and normalizes character names, detects aliases via Levenshtein distance + prefix matching (e.g. `YOUNG GILLY` → `GILLY`), infers gender hints from context.
2. **`scoring.py`** — Scores prominence with weighted metrics: 35% word share, 20% line share, 20% scene share, 15% arc spread (scenes spread across acts), 5% act presence, 5% dialogue density.
3. **`voice_inventory.py`** — Defines the voice pool: 9 native CustomVoice speakers (dylan, ryan, eric, aiden, uncle_fu, vivian, serena, ono_anna, sohee) + 21 VoiceDesign preset archetypes.
4. **`voice_designer.py`** — Generates natural-language voice descriptions for VoiceDesign TTS using rule-based heuristics (character name analysis, prominence-tier archetype inference, hardcoded overrides for known names like `MONROE`, `GILLY`).
5. **`assigner.py`** — Assigns voices by prominence tier; VoiceDesign is primary, CustomVoice is fallback. Respects per-character locks set by the user in the UI.

### core/synth/

- **`chunker.py`** — Converts `Script` + `CastingResult` into ordered `TTSJob` list. Sluglines/action go to the narrator voice; dialogue goes to the assigned character voice. Parentheticals are mapped to instruct strings (e.g. `"whispers"` → `"Speak in a quiet whisper"`). Lines >500 chars are split.
- **`engine.py`** — HTTP client that POSTs to the remote TTS server. If the server is unreachable, returns silent placeholder WAVs so the pipeline doesn't break.
- **`cache.py`** — Content-addressed cache keyed on `SHA256(text + voice_id + voice_type + instruct)`. Only changed lines re-synthesize on re-runs.
- **`assembler.py`** — Stitches chunks with context-aware silence: 1.5s scene changes, 0.5s speaker switches, 0.3s action→dialogue transitions, 0.2s same-speaker continuation.

### core/captions/

- **`srt.py`** — Generates `.srt` subtitles by tracking cumulative audio duration across chunks.
- **`json_caps.py`** — Generates `.json` captions with speaker name, element IDs, and scene numbers for programmatic use.

### app.py (Gradio UI)

Three-tab interface using `gr.State` to thread a shared state dict through callbacks:

| Tab | Purpose |
|-----|---------|
| Upload & Parse | File upload → parser dispatch → character list with stats, alias merge suggestions |
| Casting | Per-character voice selector, narrator voice selector, lock toggles |
| Generate & Play | Synthesis with live log streaming, audio player, caption display |

### scripts/tts_server.py

FastAPI server that loads both Qwen3-TTS models (CustomVoice + VoiceDesign) at startup and exposes `POST /synthesize`. This runs on the GPU machine separately from the Gradio client. It is not part of the Python package — start it manually before running the UI.

## Key Constraints

- **No LLM for parsing or casting.** All parsing is regex + bounding-box heuristics. All casting is pure Python scoring rules. Qwen3-TTS is the only ML model used.
- **Remote TTS is required for real audio.** The engine falls back to silent placeholders if `TTS_SERVER_URL` is unreachable, so the UI stays functional but produces no speech.
- **PDF parser only.** FDX/DOCX/TXT formats are stubs; implementing them requires adding parsers that produce the same `Script` model structure as `pdf_parser.py`.
- **Conda env is mandatory.** Standard `pip install` into a venv will not provide `qwen_tts` or the correct torch build.

## Reference Files

- `scriptstage-spec.md` — Full feature specification (input formats, rendering rules, caption alignment, export artifacts)
- `scriptstage-plan.md` — Original implementation plan with architecture diagrams
- `HANDOFF.md` — Executive summary and confirmed working state
- `TEST-RESULTS.md` — Stage-by-stage test results (8/8 pass, 17/17 Whisper verification)
- `.env.example` — Environment variable template (`TTS_SERVER_URL`, SSH auto-start vars)
- `test-script-unfinished-swan.pdf` — 110-page reference screenplay for integration testing
