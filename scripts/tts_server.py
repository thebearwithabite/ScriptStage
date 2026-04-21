import io
import traceback
from typing import Optional
from pathlib import Path

import uvicorn
import soundfile as sf
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

app = FastAPI(title="ScriptStage TTS Server")

# Paths as per the original scriptstage engine
CUSTOM_VOICE_PATH = Path.home() / "models" / "Qwen3-TTS-12Hz-1.7B-CustomVoice"
VOICE_DESIGN_PATH = Path.home() / "models" / "models--Qwen--Qwen3-TTS-12Hz-1.7B-VoiceDesign" / "snapshots" / "5ecdb67327fd37bb2e042aab12ff7391903235d3"

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

@app.get("/")
def read_root():
    return {"status": "ok"}

@app.post("/synthesize")
def synthesize(req: TTSRequest):
    if not req.text.strip():
        raise HTTPException(400, "Empty text provided.")
        
    try:
        audio_list = None
        sr = 24000
        
        # Determine which model to use
        # If voice_type is voice_design OR there's an instruct, use VD (if available)
        use_vd = req.voice_type == "voice_design" or (req.instruct and req.instruct.strip())
        
        if use_vd and vd_model:
            audio_list, sr = vd_model.generate_voice_design(
                text=req.text,
                instruct=req.instruct or "",
                language="english"
            )
        elif cv_model:
            audio_list, sr = cv_model.generate_custom_voice(
                text=req.text,
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
