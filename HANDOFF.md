# ScriptStage — Coding Agent Handoff

## STATUS: TTS ENGINE WORKS. BUILD THE REST.

### What's confirmed working:
- Qwen3-TTS 1.7B CustomVoice + VoiceDesign both load and generate audio
- Conda env: `qwen3-tts` (MUST activate this env)
- Model path: `/home/bear/models/Qwen3-TTS-12Hz-1.7B-CustomVoice`
- VoiceDesign path: `/home/bear/models/Qwen3-TTS-12Hz-1.7B-VoiceDesign`
- 9 speakers: aiden, dylan, eric, ono_anna, ryan, serena, sohee, uncle_fu, vivian
- 11 languages (use `"english"` lowercase or `"English"`)
- API: `Qwen3TTSModel.from_pretrained(path)` → `model.generate_custom_voice(text, speaker, language="english")`
- Sample rate: 24000 Hz
- Gradio UI runs on port 7870
- Test PDF: `test-script-unfinished-swan.pdf`
- engine.py ALREADY WORKS — loads both models, generates audio

### What's already built:
- `core/parser/` — FDX/PDF script parser (pure Python regex, NO LLM)
- `core/caster/` — Voice casting with voice_inventory.py
- `core/synth/engine.py` — TTS engine (WORKING, confirmed)
- `core/captions/` — Caption generation
- `app.py` — Gradio UI
- `core/models.py` — Data models

### Build order (from Ryan):
1. ~~TTS discovery~~ ✅ DONE
2. ~~FDX parser → internal script model~~ ✅ EXISTS
3. ~~Character extraction + deduping~~ ✅ EXISTS
4. ~~Casting algorithm + voice assignment~~ ✅ EXISTS
5. TTS rendering pipeline with chunking + caching — NEEDS TESTING
6. Caption generation — NEEDS TESTING
7. ~~FastAPI/Gradio backend~~ ✅ EXISTS (Gradio)
8. Playback UI — NEEDS TESTING
9. Additional parsers (DOCX, TXT) — NICE TO HAVE
10. Export + project run management — NEEDS TESTING

### Critical constraints:
- **NO LLM for parsing/casting** — pure Python regex and heuristics only. TTS is the only model.
- **Must run under conda env `qwen3-tts`**: `source /home/bear/miniconda3/bin/activate qwen3-tts`
- **Port 7870** for Gradio
- **Test with Unfinished Swan PDF** — it's already there

### What needs to happen:
1. End-to-end test: Upload PDF → parse → cast → synthesize → play back with captions
2. Fix any bugs in the pipeline
3. Verify all 5 existing Unfinished Swan runs have audio (or re-run one)
4. Ensure the UI shows audio player + captions
5. Report results
