#!/usr/bin/env python3
"""ScriptStage — Full-cast AI table read generator for screenplays."""

import gradio as gr
import json
import os
import time
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

# Ensure HF_HOME points to local model cache
if "HF_HOME" not in os.environ:
    os.environ["HF_HOME"] = str(Path.home() / "models")

from core.models import Script, CastingResult, ChunkResult
from core.parser import parse_script
from core.caster.characters import suggest_aliases, merge_characters, infer_gender
from core.caster.scoring import compute_prominence
from core.caster.voice_inventory import get_voice_inventory
from core.caster.assigner import assign_voices, build_cooccurrence_matrix
from core.synth.chunker import script_to_tts_jobs
from core.synth.engine import TTSEngine
from core.synth.assembler import assemble_audio
from core.synth.cache import TTSCache
from core.captions.srt import generate_srt
from core.captions.json_caps import generate_json_captions

# ── Global State ──────────────────────────────────────────────────────────────

RUNS_DIR = Path(__file__).parent / "runs"
RUNS_DIR.mkdir(exist_ok=True)

# Session state stored in gr.State
# {
#   "script": Script,
#   "casting": CastingResult,
#   "prominences": dict,
#   "run_dir": Path,
#   "chunks": list[ChunkResult],
#   "alias_suggestions": list[tuple],
#   "voice_inventory": dict,
#   "locked_voices": dict,
# }


def create_run_dir(title: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_title = "".join(c if c.isalnum() or c in "-_ " else "" for c in title)[:50].strip().replace(" ", "_")
    run_dir = RUNS_DIR / f"{ts}_{safe_title or 'untitled'}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "chunks").mkdir(exist_ok=True)
    (run_dir / "cache").mkdir(exist_ok=True)
    return run_dir


# ── Tab 1: Upload & Parse ────────────────────────────────────────────────────

def handle_upload(file):
    """Parse uploaded screenplay file."""
    if file is None:
        return None, "No file uploaded.", "", gr.update(visible=False), gr.update(visible=False)

    file_path = file.name if hasattr(file, 'name') else str(file)
    
    try:
        script = parse_script(file_path)
    except NotImplementedError as e:
        return None, f"❌ {e}", "", gr.update(visible=False), gr.update(visible=False)
    except Exception as e:
        return None, f"❌ Error parsing script: {e}", "", gr.update(visible=False), gr.update(visible=False)

    # Build summary
    ext = Path(file_path).suffix.lower()
    format_name = {".pdf": "PDF", ".fdx": "Final Draft", ".docx": "DOCX", ".txt": "Plain Text"}.get(ext, ext)
    
    summary = f"""## {script.meta.title or 'Untitled Script'}
| Metric | Value |
|--------|-------|
| Format | {format_name} |
| Est. Pages | {script.meta.page_count_estimate} |
| Scenes | {len(script.scenes)} |
| Characters | {len(script.characters)} |
| Total Elements | {len(script.elements)} |
"""

    # Character table
    chars_sorted = sorted(script.characters, key=lambda c: c.stats.words, reverse=True)
    char_table = "### Characters\n| # | Character | Lines | Words | Scenes |\n|---|-----------|-------|-------|--------|\n"
    for i, ch in enumerate(chars_sorted, 1):
        char_table += f"| {i} | {ch.name} | {ch.stats.lines} | {ch.stats.words} | {ch.stats.scenes} |\n"

    # Alias suggestions
    aliases = suggest_aliases(script.characters)
    alias_text = ""
    if aliases:
        alias_text = "### ⚠️ Alias Suggestions\n"
        for src, tgt in aliases:
            alias_text += f"- Merge **{src}** → **{tgt}**?\n"

    state = {
        "script": script.model_dump(),
        "alias_suggestions": aliases,
    }

    return (
        state,
        summary + "\n" + char_table + "\n" + alias_text,
        json.dumps(script.model_dump(), indent=2, default=str),
        gr.update(visible=True),  # continue button
        gr.update(visible=bool(aliases)),  # merge button
    )


def apply_merges(state):
    """Apply all suggested alias merges."""
    if not state or "script" not in state:
        return state, "No script loaded."
    
    script = Script.model_validate(state["script"])
    for src, tgt in state.get("alias_suggestions", []):
        script = merge_characters(script, src, tgt)
    
    state["script"] = script.model_dump()
    state["alias_suggestions"] = []
    
    # Rebuild character table
    chars_sorted = sorted(script.characters, key=lambda c: c.stats.words, reverse=True)
    char_table = f"### Characters (after merge)\n| # | Character | Lines | Words | Scenes |\n|---|-----------|-------|-------|--------|\n"
    for i, ch in enumerate(chars_sorted, 1):
        char_table += f"| {i} | {ch.name} | {ch.stats.lines} | {ch.stats.words} | {ch.stats.scenes} |\n"
    
    return state, f"✅ Merges applied. {len(script.characters)} characters remaining.\n\n{char_table}"


# ── Tab 2: Casting ───────────────────────────────────────────────────────────

def setup_casting(state):
    """Initialize casting from parsed script."""
    if not state or "script" not in state:
        return state, "No script loaded. Upload and parse first.", "", gr.update(choices=[], value=None)

    script = Script.model_validate(state["script"])
    inventory = get_voice_inventory()
    prominences = compute_prominence(script.characters, len(script.scenes))
    cooccurrence = build_cooccurrence_matrix(script.characters, script.scenes)
    
    casting = assign_voices(
        script.characters, prominences, cooccurrence, inventory, script=script
    )
    
    run_dir = create_run_dir(script.meta.title or "untitled")
    
    state["casting"] = casting.model_dump()
    state["prominences"] = prominences
    state["run_dir"] = str(run_dir)
    state["voice_inventory"] = inventory
    state["locked_voices"] = {}

    # Save casting.json
    with open(run_dir / "casting.json", "w") as f:
        json.dump(casting.model_dump(), f, indent=2, default=str)

    # Build casting display
    casting_md = build_casting_display(casting, prominences, script)

    # Voice dropdown choices
    all_voices = []
    for v in inventory["native_speakers"]:
        all_voices.append(f"{v['id']} — {v['label']}")
    for v in inventory["voice_design_presets"]:
        all_voices.append(f"{v['id']} — {v['label']}")

    # Narrator dropdown
    narrator_choices = all_voices

    return state, casting_md, json.dumps(casting.model_dump(), indent=2, default=str), gr.update(choices=narrator_choices, value=f"{casting.narrator_voice_id} — {casting.narrator_label}")


def build_casting_display(casting: CastingResult, prominences: dict, script: Script) -> str:
    md = "## 🎭 Voice Casting\n\n"
    md += f"**Narrator:** {casting.narrator_label} — *{casting.narrator_instruct}*\n\n"
    
    # Categorize roles
    leads = [(name, role) for name, role in casting.roles.items() if role.prominence >= 0.5]
    support = [(name, role) for name, role in casting.roles.items() if 0.15 <= role.prominence < 0.5]
    minor = [(name, role) for name, role in casting.roles.items() if role.prominence < 0.15]
    
    if leads:
        md += "### Lead Roles\n"
        for name, role in sorted(leads, key=lambda x: -x[1].prominence):
            md += f"- **{name}** (prominence: {role.prominence:.2f}) → {role.label}\n"
    
    if support:
        md += "\n### Supporting Roles\n"
        for name, role in sorted(support, key=lambda x: -x[1].prominence):
            md += f"- **{name}** (prominence: {role.prominence:.2f}) → {role.label}\n"
    
    if minor:
        md += "\n### Minor Roles\n"
        for name, role in sorted(minor, key=lambda x: -x[1].prominence):
            md += f"- **{name}** ({role.total_lines} lines) → {role.label}\n"
    
    return md


# ── Tab 3: Generate & Play ──────────────────────────────────────────────────

def generate_table_read(state):
    """Generate the full table read audio with captions (generator for streaming log)."""
    if not state or "script" not in state or "casting" not in state:
        yield state, "❌ No script or casting loaded.", "", None, None, None, None
        return

    script = Script.model_validate(state["script"])
    casting = CastingResult.model_validate(state["casting"])
    run_dir = Path(state["run_dir"])

    log_lines = []
    t_start = time.time()

    def log(msg):
        elapsed = time.time() - t_start
        line = f"[{elapsed:6.1f}s] {msg}"
        log_lines.append(line)

    def log_text():
        return "\n".join(log_lines)

    log("Preparing TTS jobs...")
    jobs = script_to_tts_jobs(script, casting)
    log(f"Created {len(jobs)} TTS jobs from {len(script.elements)} script elements")

    # Count by type
    type_counts = {}
    for j in jobs:
        type_counts[j.element_type] = type_counts.get(j.element_type, 0) + 1
    log(f"Job breakdown: {', '.join(f'{v} {k}' for k, v in sorted(type_counts.items()))}")

    yield state, "⏳ Synthesizing...", log_text(), None, None, None, None

    # Initialize engine and cache
    log("Loading TTS engine...")
    cache = TTSCache(run_dir / "cache")
    engine = TTSEngine()
    if engine._model:
        log("✓ CustomVoice model loaded")
    else:
        log(f"⚠ CustomVoice model not available — {engine._load_error or 'unknown error'}")
    if engine._model_vd:
        log("✓ VoiceDesign model loaded")
    else:
        log(f"⚠ VoiceDesign model not available — {engine._load_error_vd or 'unknown error'}")
    if not engine._model and not engine._model_vd:
        log("❌ NO TTS MODELS LOADED — all audio will be silent placeholders!")

    yield state, "⏳ Synthesizing...", log_text(), None, None, None, None

    # Synthesize all jobs
    chunks = []
    cache_hits = 0
    for i, job in enumerate(jobs):
        char_label = job.character or "NARRATOR"
        text_preview = job.text[:60].replace('\n', ' ')
        if len(job.text) > 60:
            text_preview += "…"

        cached_path = cache.get(cache.cache_key_for(job))
        if cached_path:
            cache_hits += 1
            chunk = ChunkResult(
                job_id=job.job_id,
                wav_path=str(cached_path),
                duration_ms=_get_wav_duration_ms(cached_path),
                trailing_silence_ms=0,
                text=job.text,
                character=job.character,
                element_ids=job.element_ids,
                scene=job.scene,
                element_type=job.element_type,
            )
            log(f"[{i+1}/{len(jobs)}] ⚡ CACHE  {char_label}: \"{text_preview}\" ({chunk.duration_ms}ms)")
        else:
            t0 = time.time()
            try:
                chunk = engine.synthesize(job, output_dir=run_dir / "chunks")
                dt = time.time() - t0
                log(f"[{i+1}/{len(jobs)}] 🔊 SYNTH  {char_label}: \"{text_preview}\" → {chunk.duration_ms}ms audio ({dt:.1f}s)")
            except Exception as e:
                import traceback
                dt = time.time() - t0
                log(f"[{i+1}/{len(jobs)}] ❌ ERROR  {char_label}: {e} ({dt:.1f}s)")
                # Create silent fallback
                wav_path = run_dir / "chunks" / f"{job.job_id}.wav"
                wav_path.parent.mkdir(parents=True, exist_ok=True)
                est_dur = max(len(job.text) / 15.0, 0.5)
                import wave as wave_mod
                with wave_mod.open(str(wav_path), "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(24000)
                    wf.writeframes(b"\x00\x00" * int(24000 * est_dur))
                chunk = ChunkResult(
                    job_id=job.job_id, wav_path=str(wav_path),
                    duration_ms=int(est_dur * 1000), text=job.text,
                    character=job.character, element_ids=job.element_ids,
                    scene=job.scene, element_type=job.element_type,
                )
            cache.put(cache.cache_key_for(job), chunk.wav_path)

        chunks.append(chunk)

        # Yield log update every chunk (Gradio streams it)
        pct = int((i + 1) / len(jobs) * 100)
        yield state, f"⏳ Synthesizing... {i+1}/{len(jobs)} ({pct}%)", log_text(), None, None, None, None

    log(f"Synthesis complete. {cache_hits} cache hits, {len(jobs) - cache_hits} synthesized.")

    # Assemble
    log("Assembling full audio...")
    t0 = time.time()
    full_audio_path = assemble_audio(chunks, run_dir)
    total_dur_ms = sum(c.duration_ms for c in chunks)
    log(f"✓ Assembled {len(chunks)} chunks → {total_dur_ms/1000:.1f}s total audio ({time.time()-t0:.1f}s)")

    yield state, "⏳ Generating captions...", log_text(), None, None, None, None

    # Captions
    log("Generating captions...")
    srt_content = generate_srt(chunks)
    json_caps = generate_json_captions(chunks)

    srt_path = run_dir / "captions.srt"
    with open(srt_path, "w") as f:
        f.write(srt_content)

    json_caps_path = run_dir / "captions.json"
    with open(json_caps_path, "w") as f:
        json.dump(json_caps, f, indent=2)

    with open(run_dir / "parsed_script.json", "w") as f:
        json.dump(script.model_dump(), f, indent=2, default=str)

    state["chunks"] = [c.model_dump() for c in chunks]

    elapsed_total = time.time() - t_start
    log(f"✅ Done in {elapsed_total:.1f}s. Output: {run_dir}")

    # Build download file list
    download_paths = []
    for fname in ["table_read_full.wav", "captions.srt", "captions.json", "casting.json", "parsed_script.json"]:
        p = run_dir / fname
        if p.exists():
            download_paths.append(str(p))

    # Final yield with all outputs populated
    yield (
        state,
        f"✅ Table read generated! {len(chunks)} segments, {total_dur_ms/1000:.1f}s audio in {elapsed_total:.1f}s",
        log_text(),
        str(full_audio_path),
        str(srt_path) if srt_path.exists() else None,
        str(json_caps_path) if json_caps_path.exists() else None,
        download_paths,
    )


def _get_wav_duration_ms(path) -> int:
    """Get WAV duration in milliseconds."""
    try:
        import soundfile as sf
        info = sf.info(str(path))
        return int(info.duration * 1000)
    except Exception:
        return 3000  # fallback estimate


# (download files are now returned directly from generate_table_read)


# ── Corner Mode CSS/JS ──────────────────────────────────────────────────────

CORNER_CSS = """
.corner-mode {
    position: fixed !important;
    bottom: 20px !important;
    right: 20px !important;
    width: 400px !important;
    max-height: 300px !important;
    z-index: 9999 !important;
    background: rgba(0,0,0,0.9) !important;
    border-radius: 12px !important;
    padding: 16px !important;
    color: white !important;
    box-shadow: 0 4px 20px rgba(0,0,0,0.5) !important;
    overflow-y: auto !important;
    resize: both !important;
}
.corner-mode .caption-current {
    font-size: 1.1em;
    font-weight: bold;
    color: #4fc3f7;
}
.corner-mode .caption-speaker {
    color: #81c784;
    font-size: 0.85em;
    text-transform: uppercase;
}
"""

CUSTOM_JS = """
function setupCornerMode() {
    const params = new URLSearchParams(window.location.search);
    if (params.get('corner') === '1') {
        document.body.classList.add('corner-active');
    }
}
document.addEventListener('DOMContentLoaded', setupCornerMode);
"""


# ── Build Gradio App ────────────────────────────────────────────────────────

def build_app():
    with gr.Blocks(
        title="ScriptStage — AI Table Read Generator",
    ) as app:
        
        gr.Markdown("# 🎭 ScriptStage\n*Upload a screenplay. Cast voices. Generate a full AI table read.*")
        
        state = gr.State({})
        
        with gr.Tabs() as tabs:
            # ── Tab 1: Upload ────────────────────────────────────────
            with gr.Tab("📁 Upload & Parse", id="upload"):
                with gr.Row():
                    with gr.Column(scale=2):
                        file_input = gr.File(
                            label="Upload Screenplay",
                            file_types=[".pdf", ".fdx", ".docx", ".txt"],
                            type="filepath",
                        )
                        parse_btn = gr.Button("Parse Script", variant="primary")
                    
                    with gr.Column(scale=3):
                        parse_output = gr.Markdown(label="Parse Results")
                
                with gr.Row():
                    merge_btn = gr.Button("✅ Apply All Merges", visible=False)
                    continue_btn = gr.Button("Continue to Casting →", variant="primary", visible=False)
                
                merge_output = gr.Markdown()
                
                with gr.Accordion("Raw JSON", open=False):
                    raw_json = gr.Code(language="json", label="Parsed Script JSON")
                
                parse_btn.click(
                    handle_upload,
                    inputs=[file_input],
                    outputs=[state, parse_output, raw_json, continue_btn, merge_btn],
                )
                merge_btn.click(
                    apply_merges,
                    inputs=[state],
                    outputs=[state, merge_output],
                )

            # ── Tab 2: Casting ───────────────────────────────────────
            with gr.Tab("🎭 Casting", id="casting"):
                casting_md = gr.Markdown()
                
                with gr.Row():
                    narrator_dropdown = gr.Dropdown(
                        label="Narrator Voice",
                        choices=[],
                        interactive=True,
                    )
                    # preview_narrator_btn = gr.Button("🔊 Preview Narrator")
                
                with gr.Accordion("Casting JSON", open=False):
                    casting_json_display = gr.Code(language="json", label="Casting JSON")
                
                generate_btn = gr.Button("🎬 Generate Table Read", variant="primary", size="lg")
                
                continue_btn.click(
                    setup_casting,
                    inputs=[state],
                    outputs=[state, casting_md, casting_json_display, narrator_dropdown],
                )

            # ── Tab 3: Generate ───────────────────────────────────────
            with gr.Tab("▶️ Generate", id="generate"):
                gen_status = gr.Markdown()

                with gr.Accordion("📋 Build Log", open=True):
                    log_viewer = gr.Textbox(
                        label="",
                        lines=18,
                        max_lines=40,
                        interactive=False,
                        autoscroll=True,
                    )

                gr.Markdown("---")
                gr.Markdown("### 🔊 Audio Output")

                audio_player = gr.Audio(
                    label="Table Read",
                    type="filepath",
                    interactive=False,
                )

                gr.Markdown("### 📥 Downloads")
                with gr.Row():
                    srt_download = gr.File(label="Captions (.srt)", interactive=False)
                    json_download = gr.File(label="Captions (.json)", interactive=False)
                download_files = gr.Files(label="All Artifacts", interactive=False)

                generate_btn.click(
                    generate_table_read,
                    inputs=[state],
                    outputs=[state, gen_status, log_viewer, audio_player, srt_download, json_download, download_files],
                )
        
        # Footer
        gr.Markdown("---\n*ScriptStage — Local AI-powered table reads. No external APIs.*")
    
    return app


if __name__ == "__main__":
    app = build_app()
    app.launch(
        server_name="0.0.0.0",
        server_port=int(os.environ.get("GRADIO_SERVER_PORT", 7870)),
        share=False,
    )
