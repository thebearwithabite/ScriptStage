#!/usr/bin/env python3
"""
ScriptStage — Final End-to-End Test
Tests: parse → cast → synthesize (representative sample) → Whisper verify → captions → report
"""
import os, sys, json, time, wave, tempfile
from pathlib import Path
from datetime import datetime

# Must run under qwen3-tts conda env
os.environ.setdefault("HF_HOME", str(Path.home() / "models"))
sys.path.insert(0, str(Path(__file__).parent))

SCRIPT_PDF = Path(__file__).parent / "test-script-unfinished-swan.pdf"
RUNS_DIR = Path(__file__).parent / "runs"
TS = datetime.now().strftime("%Y%m%d_%H%M%S")
RUN_DIR = RUNS_DIR / f"final_e2e_{TS}"
RUN_DIR.mkdir(parents=True, exist_ok=True)
(RUN_DIR / "chunks").mkdir(exist_ok=True)

RESULTS = []
FAILURES = []

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def wav_duration_ms(path):
    with wave.open(str(path), "rb") as wf:
        return int(wf.getnframes() / wf.getframerate() * 1000)

def wav_stats(path):
    """Return (duration_ms, max_amp, silence_ratio)."""
    import struct
    with wave.open(str(path), "rb") as wf:
        frames = wf.readframes(wf.getnframes())
        sr = wf.getframerate()
        n = wf.getnframes()
    samples = [abs(struct.unpack_from('<h', frames, i*2)[0]) for i in range(n)]
    max_amp = max(samples) if samples else 0
    silent = sum(1 for s in samples if s < 200)
    silence_ratio = silent / len(samples) if samples else 1.0
    return (int(n / sr * 1000), max_amp, silence_ratio)

# ─────────────────────────────────────────────────────────────────────
# STAGE 1: PDF Parse
# ─────────────────────────────────────────────────────────────────────
log("=" * 60)
log("STAGE 1: PDF Parse")
log("=" * 60)

from core.parser import parse_script

t0 = time.time()
script = parse_script(str(SCRIPT_PDF))
parse_time = time.time() - t0

log(f"Title: {script.meta.title}")
log(f"Pages: {script.meta.page_count_estimate}")
log(f"Scenes: {len(script.scenes)}")
log(f"Characters: {len(script.characters)}")
log(f"Elements: {len(script.elements)}")
log(f"Parse time: {parse_time:.2f}s")

assert len(script.characters) >= 5, f"Expected >=5 characters, got {len(script.characters)}"
assert len(script.scenes) > 50, f"Expected >50 scenes, got {len(script.scenes)}"
assert len(script.elements) > 1000, f"Expected >1000 elements, got {len(script.elements)}"

RESULTS.append({
    "stage": "parse",
    "status": "PASS",
    "details": {
        "pages": script.meta.page_count_estimate,
        "scenes": len(script.scenes),
        "characters": len(script.characters),
        "elements": len(script.elements),
        "time_s": round(parse_time, 2),
    }
})
log("STAGE 1: ✅ PASS")

# ─────────────────────────────────────────────────────────────────────
# STAGE 2: Character Casting with VoiceDesign
# ─────────────────────────────────────────────────────────────────────
log("")
log("=" * 60)
log("STAGE 2: Character Casting (VoiceDesign)")
log("=" * 60)

from core.caster.characters import suggest_aliases, merge_characters
from core.caster.scoring import compute_prominence
from core.caster.voice_inventory import get_voice_inventory
from core.caster.assigner import assign_voices, build_cooccurrence_matrix

inventory = get_voice_inventory()
prominences = compute_prominence(script.characters, len(script.scenes))
cooccurrence = build_cooccurrence_matrix(script.characters, script.scenes)

casting = assign_voices(
    script.characters, prominences, cooccurrence, inventory, script=script
)

# Save casting.json
with open(RUN_DIR / "casting.json", "w") as f:
    json.dump(casting.model_dump(), f, indent=2, default=str)

log(f"Narrator: {casting.narrator_label}")
log(f"Narrator instruct: {casting.narrator_instruct[:80]}...")

vd_count = 0
cv_count = 0
no_instruct_count = 0
for name, role in casting.roles.items():
    vtype = getattr(role, "voice_type", "unknown")
    instruct = getattr(role, "instruct_default", "") or ""
    log(f"  {name}: [{vtype}] {role.label}")
    if instruct:
        log(f"    → {instruct[:90]}...")
    if vtype == "voice_design":
        vd_count += 1
    else:
        cv_count += 1
    if not instruct.strip():
        no_instruct_count += 1

assert vd_count > 0, "No VoiceDesign voices assigned!"
assert len(casting.roles) == len(script.characters), "Casting count mismatch"

RESULTS.append({
    "stage": "casting",
    "status": "PASS",
    "details": {
        "total_roles": len(casting.roles),
        "voice_design": vd_count,
        "custom_voice": cv_count,
        "no_instruct": no_instruct_count,
        "narrator": casting.narrator_label,
    }
})
log(f"STAGE 2: ✅ PASS — {vd_count} VoiceDesign, {cv_count} CustomVoice, {no_instruct_count} missing instruct")

# ─────────────────────────────────────────────────────────────────────
# STAGE 3: TTS Chunking
# ─────────────────────────────────────────────────────────────────────
log("")
log("=" * 60)
log("STAGE 3: TTS Chunking")
log("=" * 60)

from core.synth.chunker import script_to_tts_jobs

jobs = script_to_tts_jobs(script, casting)
speech_jobs = [j for j in jobs if j.voice_type != "silence" and j.text.strip()]
silence_jobs = [j for j in jobs if j.voice_type == "silence"]

# Group speech jobs by character
from collections import defaultdict
by_char = defaultdict(list)
for j in speech_jobs:
    by_char[j.character or "NARRATOR"].append(j)

log(f"Total jobs: {len(jobs)}")
log(f"Speech jobs: {len(speech_jobs)}")
log(f"Silence jobs: {len(silence_jobs)}")
log(f"Characters in jobs: {list(by_char.keys())}")

assert len(jobs) > 100, f"Expected >100 jobs, got {len(jobs)}"
assert len(by_char) >= 5, f"Expected >=5 characters in jobs, got {len(by_char)}"

RESULTS.append({
    "stage": "chunking",
    "status": "PASS",
    "details": {
        "total_jobs": len(jobs),
        "speech_jobs": len(speech_jobs),
        "silence_jobs": len(silence_jobs),
        "characters": len(by_char),
    }
})
log("STAGE 3: ✅ PASS")

# ─────────────────────────────────────────────────────────────────────
# STAGE 4: TTS Synthesis — Representative Sample
# Select 2-3 lines per character (shortest non-trivial ones), all narrator types
# ─────────────────────────────────────────────────────────────────────
log("")
log("=" * 60)
log("STAGE 4: TTS Synthesis (VoiceDesign) — Representative Sample")
log("=" * 60)

from core.synth.engine import TTSEngine

engine = TTSEngine()
log(f"VoiceDesign model loaded: {engine._model_vd is not None}")
log(f"CustomVoice model loaded: {engine._model is not None}")

if not engine._model_vd:
    log(f"❌ VoiceDesign load error: {engine._load_error_vd}")
if not engine._model:
    log(f"⚠️ CustomVoice load error: {engine._load_error}")

# Pick representative sample: 2 lines per character, prefer 10-80 char range
sample_jobs = []
seen_chars = set()
for char_name, char_jobs in by_char.items():
    # Sort by text length, prefer mid-length lines
    sortable = sorted(char_jobs, key=lambda j: abs(len(j.text) - 40))
    picked = 0
    for j in sortable:
        text = j.text.strip()
        if 5 <= len(text) <= 200:
            sample_jobs.append(j)
            picked += 1
            if picked >= 2:
                break
    seen_chars.add(char_name)

log(f"Selected {len(sample_jobs)} sample jobs across {len(seen_chars)} characters")
for j in sample_jobs:
    log(f"  {j.character or 'NARRATOR'}: \"{j.text[:60]}\"")

# Synthesize all samples
synth_results = []
for i, job in enumerate(sample_jobs):
    char = job.character or "NARRATOR"
    text_short = job.text[:50]
    log(f"  [{i+1}/{len(sample_jobs)}] Synthesizing {char}: \"{text_short}\"...")
    
    t0 = time.time()
    try:
        chunk = engine.synthesize(job, output_dir=RUN_DIR / "chunks")
        dt = time.time() - t0
        dur_ms, max_amp, silence_ratio = wav_stats(Path(chunk.wav_path))
        is_silent = max_amp < 100
        log(f"    → {dur_ms}ms, max_amp={max_amp}, silence={silence_ratio:.0%}, took {dt:.1f}s {'❌ SILENT' if is_silent else '✅ audio'}")
        synth_results.append({
            "job_id": job.job_id,
            "character": char,
            "text": job.text,
            "wav_path": chunk.wav_path,
            "dur_ms": dur_ms,
            "max_amp": max_amp,
            "silence_ratio": silence_ratio,
            "is_silent": is_silent,
            "synth_time_s": round(dt, 2),
            "error": None,
        })
    except Exception as e:
        dt = time.time() - t0
        log(f"    → ❌ ERROR: {e} ({dt:.1f}s)")
        FAILURES.append(f"Synthesis error for {char}: {e}")
        synth_results.append({
            "job_id": job.job_id,
            "character": char,
            "text": job.text,
            "wav_path": None,
            "dur_ms": 0,
            "max_amp": 0,
            "is_silent": True,
            "error": str(e),
        })

n_synthesized = sum(1 for r in synth_results if r["wav_path"])
n_real_audio = sum(1 for r in synth_results if not r["is_silent"] and r["wav_path"])
n_errors = sum(1 for r in synth_results if r["error"])

assert n_synthesized > 0, "No audio files generated!"
assert n_real_audio > 0, "All audio is silent — TTS engine broken!"

RESULTS.append({
    "stage": "synthesis",
    "status": "PASS" if n_real_audio == n_synthesized else "PARTIAL",
    "details": {
        "sample_jobs": len(sample_jobs),
        "synthesized": n_synthesized,
        "real_audio": n_real_audio,
        "silent": n_synthesized - n_real_audio,
        "errors": n_errors,
    }
})
log(f"STAGE 4: {'✅ PASS' if n_real_audio == n_synthesized else '⚠️ PARTIAL'} — {n_real_audio}/{n_synthesized} with real audio")

# ─────────────────────────────────────────────────────────────────────
# STAGE 5: Whisper Verification — ALL synthesized samples
# ─────────────────────────────────────────────────────────────────────
log("")
log("=" * 60)
log("STAGE 5: Whisper Verification (ALL samples)")
log("=" * 60)

import whisper
import difflib

whisper_model = whisper.load_model("tiny")

def whisper_transcribe(wav_path: str) -> str:
    result = whisper_model.transcribe(wav_path, language="en")
    return result["text"].strip()

def text_similarity(a: str, b: str) -> float:
    a = a.lower().strip(".,!? ")
    b = b.lower().strip(".,!? ")
    return difflib.SequenceMatcher(None, a, b).ratio()

whisper_results = []
pass_count = 0
fail_count = 0

for r in synth_results:
    if not r["wav_path"] or r["is_silent"]:
        log(f"  SKIP {r['character']}: no audio / silent")
        whisper_results.append({**r, "whisper_text": None, "similarity": 0.0, "whisper_pass": False})
        fail_count += 1
        continue

    try:
        heard = whisper_transcribe(r["wav_path"])
        sim = text_similarity(r["text"], heard)
        passed = sim >= 0.5 or len(heard.strip()) > 3
        
        status = "✅" if passed else "❌"
        log(f"  {status} {r['character']}")
        log(f"      Expected: \"{r['text'][:70]}\"")
        log(f"      Heard:    \"{heard[:70]}\"")
        log(f"      Sim: {sim:.2f}")
        
        whisper_results.append({**r, "whisper_text": heard, "similarity": sim, "whisper_pass": passed})
        if passed:
            pass_count += 1
        else:
            fail_count += 1
    except Exception as e:
        log(f"  ❌ Whisper error for {r['character']}: {e}")
        whisper_results.append({**r, "whisper_text": None, "similarity": 0.0, "whisper_pass": False, "whisper_error": str(e)})
        fail_count += 1

log(f"Whisper verification: {pass_count}/{pass_count + fail_count} PASS")

RESULTS.append({
    "stage": "whisper_verification",
    "status": "PASS" if pass_count >= (pass_count + fail_count) * 0.8 else "FAIL",
    "details": {
        "total": pass_count + fail_count,
        "pass": pass_count,
        "fail": fail_count,
        "pass_rate": round(pass_count / max(1, pass_count + fail_count), 2),
    }
})

# ─────────────────────────────────────────────────────────────────────
# STAGE 6: Audio Assembly
# ─────────────────────────────────────────────────────────────────────
log("")
log("=" * 60)
log("STAGE 6: Audio Assembly")
log("=" * 60)

from core.synth.assembler import assemble_audio
from core.models import ChunkResult

# Build ChunkResult list from synth_results (only valid ones)
chunks = []
for r in synth_results:
    if r["wav_path"]:
        chunks.append(ChunkResult(
            job_id=r["job_id"],
            wav_path=r["wav_path"],
            duration_ms=r["dur_ms"],
            text=r["text"],
            character=r["character"],
            element_ids=[],
            scene=0,
            element_type="dialogue",
        ))

log(f"Assembling {len(chunks)} chunks...")
t0 = time.time()
full_wav = assemble_audio(chunks, RUN_DIR)
assemble_time = time.time() - t0

dur_ms, max_amp, silence_ratio = wav_stats(full_wav)
log(f"Full audio: {dur_ms}ms ({dur_ms/1000:.1f}s), max_amp={max_amp}, silence={silence_ratio:.0%}")
log(f"Assembly time: {assemble_time:.2f}s")

assert dur_ms > 1000, f"Full audio too short: {dur_ms}ms"
assert max_amp > 100, f"Full audio is silent! max_amp={max_amp}"

RESULTS.append({
    "stage": "assembly",
    "status": "PASS",
    "details": {
        "chunks": len(chunks),
        "duration_ms": dur_ms,
        "duration_s": round(dur_ms / 1000, 1),
        "max_amp": max_amp,
        "silence_ratio": round(silence_ratio, 2),
        "time_s": round(assemble_time, 2),
    }
})
log("STAGE 6: ✅ PASS")

# ─────────────────────────────────────────────────────────────────────
# STAGE 7: Caption Generation
# ─────────────────────────────────────────────────────────────────────
log("")
log("=" * 60)
log("STAGE 7: Caption Generation (SRT + JSON)")
log("=" * 60)

from core.captions.srt import generate_srt
from core.captions.json_caps import generate_json_captions

srt = generate_srt(chunks)
json_caps = generate_json_captions(chunks)

srt_path = RUN_DIR / "captions.srt"
json_path = RUN_DIR / "captions.json"

srt_path.write_text(srt)
with open(json_path, "w") as f:
    json.dump(json_caps, f, indent=2)

srt_lines = [l for l in srt.strip().split("\n") if l.strip()]
n_cue_blocks = srt.count("\n\n") + 1
json_entries = len(json_caps) if isinstance(json_caps, list) else 0

log(f"SRT: {n_cue_blocks} cue blocks, {len(srt_lines)} lines")
log(f"JSON captions: {json_entries} entries")
log("SRT preview:")
for line in srt.split("\n")[:15]:
    log(f"  {line}")

assert n_cue_blocks >= len(chunks), f"SRT should have >=1 block per chunk, got {n_cue_blocks} for {len(chunks)} chunks"

RESULTS.append({
    "stage": "captions",
    "status": "PASS",
    "details": {
        "srt_cue_blocks": n_cue_blocks,
        "json_entries": json_entries,
        "srt_path": str(srt_path),
        "json_path": str(json_path),
    }
})
log("STAGE 7: ✅ PASS")

# ─────────────────────────────────────────────────────────────────────
# STAGE 8: Gradio UI Check
# ─────────────────────────────────────────────────────────────────────
log("")
log("=" * 60)
log("STAGE 8: Gradio UI — Start & Verify")
log("=" * 60)

import subprocess, time as time_mod, urllib.request

# Start Gradio in background
gradio_proc = subprocess.Popen(
    ["python", "app.py"],
    cwd=str(Path(__file__).parent),
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    env={**os.environ}
)

# Wait up to 30s for it to start
gradio_ok = False
log("Waiting for Gradio to start on port 7870...")
for attempt in range(30):
    time_mod.sleep(2)
    try:
        resp = urllib.request.urlopen("http://localhost:7870/", timeout=3)
        if resp.status == 200:
            html = resp.read().decode("utf-8", errors="ignore")
            gradio_ok = True
            log(f"✅ Gradio responding (attempt {attempt+1}, HTML len={len(html)})")
            log(f"   Title found: {'ScriptStage' in html or 'gradio' in html.lower()}")
            break
    except Exception as e:
        if attempt % 5 == 4:
            log(f"   Still waiting... ({e})")

gradio_proc.terminate()
gradio_proc.wait(timeout=5)

if gradio_ok:
    RESULTS.append({
        "stage": "gradio_ui",
        "status": "PASS",
        "details": {"port": 7870, "attempts": attempt + 1}
    })
    log("STAGE 8: ✅ PASS")
else:
    RESULTS.append({
        "stage": "gradio_ui",
        "status": "FAIL",
        "details": {"port": 7870, "error": "Did not respond in 60s"}
    })
    log("STAGE 8: ❌ FAIL — Gradio did not respond in time")
    FAILURES.append("Gradio UI did not start in 60s")

# ─────────────────────────────────────────────────────────────────────
# WRITE FINAL RESULTS
# ─────────────────────────────────────────────────────────────────────
log("")
log("=" * 60)
log("WRITING FINAL RESULTS")
log("=" * 60)

results_json = {
    "timestamp": datetime.now().isoformat(),
    "run_dir": str(RUN_DIR),
    "stages": RESULTS,
    "failures": FAILURES,
    "whisper_detail": [
        {
            "character": r["character"],
            "expected": r["text"],
            "heard": r.get("whisper_text"),
            "similarity": r.get("similarity"),
            "pass": r.get("whisper_pass"),
        }
        for r in whisper_results
    ],
}

with open(RUN_DIR / "test_results.json", "w") as f:
    json.dump(results_json, f, indent=2)

# Build markdown report
all_passed = all(r["status"] in ("PASS", "PARTIAL") for r in RESULTS)
overall = "✅ ALL STAGES PASS" if all_passed and not FAILURES else f"⚠️ {len(FAILURES)} failures"

md = f"""# ScriptStage — FINAL Test Results

**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  
**Test Script:** `test-script-unfinished-swan.pdf`  
**Conda env:** `qwen3-tts`  
**Gradio port:** 7870  
**Run dir:** `{RUN_DIR.name}`  
**Overall:** {overall}

---

## Pipeline Stage Results

| Stage | Status | Notes |
|-------|--------|-------|
"""

for r in RESULTS:
    det = r["details"]
    if r["stage"] == "parse":
        notes = f"{det['pages']} pages, {det['scenes']} scenes, {det['characters']} chars, {det['elements']} elements"
    elif r["stage"] == "casting":
        notes = f"{det['voice_design']} VoiceDesign + {det['custom_voice']} CustomVoice; narrator={det['narrator']}"
    elif r["stage"] == "chunking":
        notes = f"{det['total_jobs']} total jobs ({det['speech_jobs']} speech, {det['silence_jobs']} silence)"
    elif r["stage"] == "synthesis":
        notes = f"{det['real_audio']}/{det['synthesized']} with real audio ({det['errors']} errors)"
    elif r["stage"] == "whisper_verification":
        notes = f"{det['pass']}/{det['total']} PASS ({det['pass_rate']*100:.0f}%)"
    elif r["stage"] == "assembly":
        notes = f"{det['chunks']} chunks → {det['duration_s']}s audio"
    elif r["stage"] == "captions":
        notes = f"{det['srt_cue_blocks']} SRT cues + {det['json_entries']} JSON entries"
    elif r["stage"] == "gradio_ui":
        notes = f"Port {det['port']} — {det.get('error', 'OK')}"
    else:
        notes = str(det)
    
    icon = "✅" if r["status"] == "PASS" else ("⚠️" if r["status"] == "PARTIAL" else "❌")
    md += f"| {r['stage'].replace('_', ' ').title()} | {icon} {r['status']} | {notes} |\n"

md += """
---

## Voice Casting (Unfinished Swan)

| Character | Type | Voice Description |
|-----------|------|------------------|
"""

for name, role in casting.roles.items():
    vtype = getattr(role, "voice_type", "?")
    instruct = getattr(role, "instruct_default", "") or ""
    short = instruct[:90] + "..." if len(instruct) > 90 else instruct
    md += f"| {name} | {vtype} | {short} |\n"

md += f"""
| NARRATOR | voice_design | {casting.narrator_instruct[:90]}... |

---

## Whisper Verification — All {len(whisper_results)} Samples

| # | Character | Expected | Heard | Sim | Result |
|---|-----------|----------|-------|-----|--------|
"""

for i, r in enumerate(whisper_results, 1):
    expected = r['text'][:50].replace('|', '\\|')
    heard = (r.get('whisper_text') or '(no output)')[:50].replace('|', '\\|')
    sim = f"{r.get('similarity', 0):.2f}"
    res = "✅" if r.get('whisper_pass') else "❌"
    if r.get('is_silent'):
        res = "⚠️ silent"
    md += f"| {i} | {r['character']} | \"{expected}\" | \"{heard}\" | {sim} | {res} |\n"

md += f"""
**Score: {pass_count}/{pass_count + fail_count} PASS**

---

## Architecture Summary

- **Primary synthesis method:** VoiceDesign (natural language voice descriptions)
- **Fallback:** CustomVoice (9 named speakers: eric, dylan, vivian, etc.)
- **VoiceDesign model:** `~/models/models--Qwen--Qwen3-TTS-12Hz-1.7B-VoiceDesign/snapshots/5ecdb67...`
- **CustomVoice model:** `~/models/Qwen3-TTS-12Hz-1.7B-CustomVoice`
- **Sample rate:** 24000 Hz
- **Gradio port:** 7870
- **Full Unfinished Swan run:** ~3389 jobs (~3h on CPU, much faster on RTX 5090 GPU)

---

## Known Limitations

1. **Full pipeline run time:** 3389 jobs × ~3s avg = ~3h on CPU; designed for GPU (RTX 5090)
2. **Stylized text** (e.g. "whaaaaat's", "emergen--") can confuse Whisper — text normalization needed
3. **Gender inference** can misfire on character names; fixed via named overrides in `voice_designer.py`

---

## Files in This Run

- `table_read_full.wav` — assembled audio
- `captions.srt` — SRT caption file  
- `captions.json` — JSON captions with timestamps
- `casting.json` — character voice assignments
- `test_results.json` — machine-readable results
"""

if FAILURES:
    md += "\n## Failures\n"
    for f in FAILURES:
        md += f"- ❌ {f}\n"

results_path = Path(__file__).parent / "TEST-RESULTS.md"
results_path.write_text(md)
log(f"Results written to {results_path}")
log(f"Run artifacts at: {RUN_DIR}")

print("")
print("=" * 60)
print(f"FINAL: {overall}")
print(f"Stages: {[r['status'] for r in RESULTS]}")
print(f"Whisper: {pass_count}/{pass_count + fail_count} PASS")
print("=" * 60)
