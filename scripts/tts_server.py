import io
import json
import os
import traceback
from typing import Optional
from pathlib import Path
import urllib.request
import urllib.error

import uvicorn
import soundfile as sf
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from core.director import DirectorOptions, enhance_dialogue_line

app = FastAPI(title="ScriptStage TTS Server")
# Example request payload:
# {
#   "text": "I can't believe you did that!",
#   "voice_type": "voice_design",
#   "backend": "auto",
#   "apply_director": true,
#   "emotion": "appalled",
#   "style": "dramatic",
#   "voice": "lead_female",
#   "tags_before": ["sighs"]
# }

# Paths as per the original scriptstage engine
CUSTOM_VOICE_PATH = Path.home() / "models" / "Qwen3-TTS-12Hz-1.7B-CustomVoice"
VOICE_DESIGN_PATH = Path.home() / "models" / "models--Qwen--Qwen3-TTS-12Hz-1.7B-VoiceDesign" / "snapshots" / "5ecdb67327fd37bb2e042aab12ff7391903235d3"
DRAMABOX_MODEL_ID = os.environ.get("DRAMABOX_MODEL_ID", "ResembleAI/Dramabox")
DRAMABOX_API_URL = os.environ.get(
    "DRAMABOX_API_URL",
    f"https://api-inference.huggingface.co/models/{DRAMABOX_MODEL_ID}",
)
DRAMABOX_API_TOKEN = os.environ.get("DRAMABOX_API_TOKEN", "")

cv_model = None
vd_model = None

@app.on_event("startup")
def load_models():
    global cv_model, vd_model
    try:
        from qwen_tts import Qwen3TTSModel
    except ImportError:
        print("❌ Error: 'qwen_tts' package not found. Please install it in this environment.")
        return

    print("Loading CustomVoice model...")
    try:
        cv_model = Qwen3TTSModel.from_pretrained(str(CUSTOM_VOICE_PATH), device_map="auto")
        print("✅ CustomVoice model loaded.")
    except Exception as e:
        print(f"⚠️ CustomVoice failed to load from {CUSTOM_VOICE_PATH}: {e}")

    print("Loading VoiceDesign model...")
    try:
        vd_model = Qwen3TTSModel.from_pretrained(str(VOICE_DESIGN_PATH), device_map="auto")
        print("✅ VoiceDesign model loaded.")
    except Exception as e:
        print(f"⚠️ VoiceDesign failed to load from {VOICE_DESIGN_PATH}: {e}")

class TTSRequest(BaseModel):
    text: str
    voice_type: str  # "native" or "voice_design"
    speaker: Optional[str] = None
    instruct: Optional[str] = None
    backend: str = "auto"  # auto | dramabox | qwen
    apply_director: bool = True
    emotion: Optional[str] = None
    style: Optional[str] = None
    voice: Optional[str] = None
    tags_before: list[str] = Field(default_factory=list)
    tags_after: list[str] = Field(default_factory=list)


def _synthesize_dramabox(directed_text: str) -> tuple[bytes, str]:
    payload = {"inputs": directed_text, "options": {"wait_for_model": True}}
    headers = {"Content-Type": "application/json"}
    if DRAMABOX_API_TOKEN:
        headers["Authorization"] = f"Bearer {DRAMABOX_API_TOKEN}"

    req = urllib.request.Request(
        DRAMABOX_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as response:
        content_type = response.headers.get("Content-Type", "audio/wav")
        data = response.read()
        if "application/json" in content_type:
            message = json.loads(data.decode("utf-8"))
            raise RuntimeError(f"Dramabox error: {message}")
        return data, content_type

@app.get("/")
def read_root():
    return {"status": "ok"}

@app.post("/synthesize")
def synthesize(req: TTSRequest):
    if not req.text.strip():
        raise HTTPException(400, "Empty text provided.")
        
    try:
        directed_text = req.text
        if req.apply_director:
            directed_text = enhance_dialogue_line(
                req.text,
                DirectorOptions(
                    emotion=req.emotion,
                    style=req.style,
                    voice=req.voice,
                    tags_before=req.tags_before,
                    tags_after=req.tags_after,
                ),
            )

        preferred_backend = (req.backend or "auto").lower()
        if preferred_backend in {"auto", "dramabox"}:
            try:
                audio_bytes, media_type = _synthesize_dramabox(directed_text)
                return Response(content=audio_bytes, media_type=media_type)
            except Exception as dramabox_error:
                print(f"⚠️ Dramabox synthesis failed, falling back to Qwen path: {dramabox_error}")
                if preferred_backend == "dramabox" and not (cv_model or vd_model):
                    raise

        audio_list = None
        sr = 24000
        
        # Determine which model to use
        # If voice_type is voice_design OR there's an instruct, use VD (if available)
        use_vd = req.voice_type == "voice_design" or (req.instruct and req.instruct.strip())
        
        if use_vd and vd_model:
            audio_list, sr = vd_model.generate_voice_design(
                text=directed_text,
                instruct=req.instruct or "",
                language="english"
            )
        elif cv_model:
            audio_list, sr = cv_model.generate_custom_voice(
                text=directed_text,
                speaker=req.speaker or "eric",
                language="english",
                instruct=req.instruct or None
            )
        else:
            raise HTTPException(500, "No TTS models loaded on server.")
            
        if not audio_list:
            raise HTTPException(500, "Model inference returned no audio.")
            
        # Convert raw audio array to WAV bytes
        buf = io.BytesIO()
        sf.write(buf, audio_list[0], sr, format='WAV')
        buf.seek(0)
        return Response(content=buf.read(), media_type="audio/wav")
        
    except Exception as e:
        print("Error during synthesis:")
        traceback.print_exc()
        raise HTTPException(500, str(e))

if __name__ == "__main__":
    # Listen on all interfaces so the Mac can reach it over Tailscale
    uvicorn.run(app, host="0.0.0.0", port=8000)
