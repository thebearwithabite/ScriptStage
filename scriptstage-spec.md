# ScriptStage — Full Spec

## Goal
Build a local application that lets Ryan upload a screenplay file (FDX/DOCX/PDF/TXT), automatically parses it into structured screenplay elements, performs automatic casting (character detection + voice assignment), synthesizes a full-cast table read using qwen3-tts with consistent voices per role, and plays it back in a minimal always-available UI: a small corner overlay with captions synced to audio, default playback rate 1.25x.

## Non-negotiables

Do not "MVP past" casting. Casting must be a first-class system:
- character extraction with deduping/alias handling
- line/word counts per role
- automatic voice assignment using a repeatable scoring algorithm
- manual override per character
- voice preview for each character
- maintain consistent voice per character across entire script

Output must include:
- synthesized audio (single combined file plus chunk files)
- captions (SRT and JSON)
- a runnable UI to listen + read captions

**Local-only. No external APIs.**

## Hardware/OS
WSL on RTX 5090 machine. Use GPU if available.

## User Experience

User opens http://localhost:7860 (or similar).

Upload script. App shows:
- detected title, page count (approx), scenes
- character list with: total lines, total words, scenes present, assigned voice profile, preview button

User can adjust casting quickly (dropdown voices, narrator voice, remove minor roles).

Click **Generate Table Read**.

App starts playing within 30–90 seconds (streaming from chunks).

Captions appear in a compact overlay mode:
- optional "corner mode" (fixed position, resizable)
- highlighted current line
- previous/next scene buttons

Playback rate default: 1.25x, user can adjust.

## Supported input formats

Priority order:
- **FDX** (Final Draft XML): best structured parse
- **DOCX**: use paragraph styles + heuristics
- **PDF**: attempt text extraction; if likely scanned, show warning and allow user to upload TXT/DOCX/FDX instead (do not build full OCR pipeline unless easy)
- **TXT**: fountain-like / plain text heuristics

## Core features

### A) Script parsing into structured model

Create internal model:
```json
{
  "meta": { "title": "", "page_count_estimate": 0 },
  "elements": [
    {"id":"e1","type":"slug","text":"EXT. ...","scene":1},
    {"id":"e2","type":"action","text":"...","scene":1},
    {"id":"e3","type":"character","text":"MONROE","scene":1},
    {"id":"e4","type":"parenthetical","text":"(whispers)","scene":1},
    {"id":"e5","type":"dialogue","text":"Thanks, Fred!","scene":1}
  ],
  "characters": [
    {"name":"MONROE","aliases":["Monroe"],"stats":{"lines":120,"words":8200,"scenes":38}}
  ],
  "scenes":[
    {"scene":1,"slug":"EXT. ...","start_element":"e1","end_element":"e88"}
  ]
}
```

### B) Character extraction + alias handling

Requirements:
- Character names are usually ALL CAPS cues.
- Deduplicate: strip punctuation
- treat "MONROE (O.S.)" / "MONROE (V.O.)" / "MONROE (CONT'D)" as MONROE
- treat "YOUNG MONROE" as distinct unless user merges
- Identify minor one-liners and group into "VARIOUS" if user chooses.
- Provide merge UI: "Merge 'YOUNG MONROE' into 'MONROE'" with one click.

### C) Casting system (do not skimp)

Casting is a pipeline with scoring.

**Voice inventory**

Define a voice library that qwen3-tts can produce. There are 3 acceptable approaches:
1. If qwen3-tts supports discrete speakers/voice IDs: enumerate speaker IDs, map to human-readable labels
2. If it supports voice "styles" or embeddings: precompute a small set of embedding presets, store in voices/ folder
3. If it supports only one base voice: create distinct "voice profiles" by varying parameters (speed, pitch, energy, formant shift if supported) and by applying light postprocessing filters (ffmpeg) to differentiate.

Claude must detect which case applies by probing the installed qwen3-tts interface. The system must still provide distinct character voices.

**Narrator vs characters**
- Narrator voice: neutral male by default (configurable)
- Character voices: assigned uniquely for all characters above a threshold of dialogue (e.g., > 20 lines). Minor roles can share voices.

**Casting algorithm (must be implemented)**

For each character, compute:
- prominence score = weighted function of lines, words, scenes
- dialog density and average line length
- presence across act structure (approx: early/mid/late scenes)

Then assign voices using:
- constraint: leads must have distinct voices (no collisions)
- constraint: avoid assigning similar voices in the same scene when possible
- preference: allocate "best" voices to top roles

Implement voice similarity: if discrete voices exist, estimate similarity using speaker embeddings if available; otherwise fallback to "avoid reusing same voice for top N roles".

**Casting output**

Produce casting.json like:
```json
{
  "narrator": {"voice_id":"narr_male_01", "label":"Neutral Male"},
  "roles": {
    "MONROE": {"voice_id":"char_male_young_03","label":"Young Male 3","prominence":0.92},
    "GILLY": {"voice_id":"char_female_young_02","label":"Young Female 2","prominence":0.71}
  },
  "shared_pool": ["support_01","support_02","support_03"]
}
```

Voice preview UI must have "Preview" button that generates ~8–12 seconds for the selected character using a representative sample line.

### D) Script-to-performance rendering

Convert parsed script into TTS segments.

Rules:
- Sluglines: narrator reads quickly and slightly quieter
- Action: narrator reads, slightly faster
- Dialogue: character voice reads
- Parenthetical: either narrator reads in aside voice OR same character voice but quiet and bracketed
- Insert SSML-like pauses if supported. If not, insert punctuation-based pauses.

Segmenting: chunk by scene and further by ~20–40 seconds of audio per chunk. Each chunk yields:
- `chunks/0001.wav`
- caption lines with timestamps
- metadata: which elements covered

### E) Captions + alignment

Because TTS won't inherently provide word-level timestamps, do chunk-level line alignment:

- Each TTS line becomes one caption entry.
- Estimate duration per line based on: synthesized audio duration returned by wav metadata; allocate line boundaries proportionally by characters/words if multiple lines combined
- Prefer generating one audio clip per "caption line" (dialogue line or action paragraph). This makes alignment exact and avoids guessing.

Outputs:
- `captions.srt`
- `captions.json` with: start/end ms, text, speaker, element IDs

### F) Playback UI

Build a local web UI. Requirements:
- Shows audio player
- Default playback rate 1.25x
- Captions view: current caption highlighted, scroll follow, show speaker name
- "Corner overlay mode": minimal chrome, resizable, position fixed bottom-right, toggle with a button or URL param `?corner=1`
- Controls: play/pause, next/prev scene, jump to scene, speed slider (default 1.25)

### G) Performance and caching

- Cache TTS results by hash of: text + voice profile + settings
- If user changes a voice for one character, regenerate only affected lines.

### H) Export + artifacts

After generation:
- Provide download links:
  - combined full audio `table_read_full.wav` (and optionally mp3)
  - `captions.srt`
  - `parsed_script.json`
  - `casting.json`
- Store each project run in `runs/<timestamp>_<scriptname>/`
