# ScriptStage Director Instructions (Dramabox + Audio Tags)

Use this as reusable system guidance for LLM or programmatic dialogue direction.

## Goal
- Preserve original dialogue text exactly.
- Add voice-only square bracket tags like `[sighs]`, `[thoughtful]`.
- Optionally add Dramabox semantic tokens like `{emotion=}`, `{style=}`, `{voice=}`.

## Rules
1. Do not alter or rewrite dialogue words.
2. Only add tags/tokens around the line.
3. Use voice-only tags (no music/SFX/non-audio stage directions).
4. Keep tags context-appropriate and non-contradictory.
5. Prefer concise tagging (1–3 tags per line unless needed).

## Supported Direction Formats
- ScriptStage audio tags: `[happy]`, `[sad]`, `[excited]`, `[angry]`, `[whisper]`, `[thoughtful]`, `[laughing]`, `[sighs]`, `[short pause]`, `[long pause]`
- Dramabox semantic tokens: `{emotion=joy}`, `{style=dramatic}`, `{voice=lead_female}`

## Recommended Line Pattern
`{emotion=<emotion>} {style=<style>} {voice=<voice>} [tag] Original line text [tag]`

Example:
`{emotion=appalled} {style=cinematic} {voice=lead_female} [sighs] I can't believe you did that!`

## FastAPI Usage (Android-friendly)
`POST /synthesize`

```json
{
  "text": "Are you serious?",
  "voice_type": "voice_design",
  "speaker": "eric",
  "instruct": "Speak naturally",
  "backend": "auto",
  "apply_director": true,
  "emotion": "surprised",
  "style": "dramatic",
  "voice": "lead_female",
  "tags_before": ["appalled"],
  "tags_after": ["sighs"]
}
```

- `backend="auto"` tries Dramabox first, then falls back to existing Qwen path.
- Keep Android client simple: upload text/script chunks, call this route, stream/play returned WAV.

## Model Reference
- Dramabox model page: https://huggingface.co/ResembleAI/Dramabox

## Future Improvements
- Add an LLM-based “Director pass” that predicts tags from scene/character context.
- Add per-character style memory so emotion/style can evolve over story arcs.
