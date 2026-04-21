"""TTS synthesis engine — Client for remote WSL TTS Server."""

from __future__ import annotations

import os
import json
import wave
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

from core.models import ChunkResult, TTSJob

SAMPLE_RATE = 24000

# Fallback native speaker pool per gender
_FALLBACK_BY_GENDER = {
    "male":    ["eric", "ryan", "dylan", "aiden", "uncle_fu"],
    "female":  ["vivian", "serena", "ono_anna", "sohee"],
    "unknown": ["eric", "vivian", "ryan", "serena"],
}

def _generate_silent_wav(duration_s: float, path: Path) -> None:
    n_frames = int(SAMPLE_RATE * duration_s)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(b"\x00\x00" * n_frames)

def _wav_duration_ms(path: Path) -> int:
    with wave.open(str(path), "rb") as wf:
        return int(wf.getnframes() / wf.getframerate() * 1000)

def _postprocess(wav_path: Path) -> Path:
    """Trim silence and normalize. Best-effort with pydub."""
    try:
        from pydub import AudioSegment
        from pydub.effects import normalize
        from pydub.silence import detect_leading_silence

        audio = AudioSegment.from_wav(str(wav_path))
        lead = detect_leading_silence(audio, silence_threshold=-40)
        trail = detect_leading_silence(audio.reverse(), silence_threshold=-40)
        end = len(audio) - trail
        if end > lead:
            audio = audio[lead:end]
        audio = normalize(audio)
        audio.export(str(wav_path), format="wav")
    except ImportError:
        pass
    return wav_path

class TTSEngine:
    """Synthesizes audio chunks via HTTP requests to the WSL server."""

    def __init__(self, server_url: Optional[str] = None) -> None:
        import dotenv
        dotenv.load_dotenv()
        
        # Default to your WSL Tailscale IP on port 8000
        self.server_url = server_url or os.environ.get("TTS_SERVER_URL", "http://127.0.0.1:8000")
        if self.server_url.endswith("/"):
            self.server_url = self.server_url[:-1]
            
        # Mocking these so app.py thinks models are loaded
        self._model = "Remote Server"
        self._model_vd = "Remote Server"
        self._load_error = None
        self._load_error_vd = None

    def start_remote_server(self, log_callback=None) -> None:
        """Attempt to start the remote server via SSH if configured."""
        cmd = os.environ.get("TTS_SSH_START_CMD")
        if not cmd:
            return
            
        import subprocess
        import time
        import urllib.request
        
        if log_callback: log_callback("🚀 Spinning up remote GPU server (this takes ~15 seconds)...")
        subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Wait for the server to become available
        max_retries = 30
        for i in range(max_retries):
            try:
                # Just ping the root to see if uvicorn is responding
                req = urllib.request.Request(self.server_url)
                with urllib.request.urlopen(req, timeout=1):
                    pass
                if log_callback: log_callback("✅ Remote server is online and models are loaded!")
                return
            except Exception:
                time.sleep(1)
        if log_callback: log_callback("⚠️ Remote server didn't respond in time. Generations may fail.")

    def stop_remote_server(self, log_callback=None) -> None:
        """Attempt to stop the remote server via SSH if configured."""
        cmd = os.environ.get("TTS_SSH_STOP_CMD")
        if not cmd:
            return
            
        import subprocess
        if log_callback: log_callback("🛑 Shutting down remote GPU server to free VRAM...")
        subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


    def _fallback_speaker(self, job: TTSJob) -> str:
        """Pick the best native fallback speaker for a job."""
        gender = job.gender_hint if hasattr(job, "gender_hint") else "unknown"
        pool = _FALLBACK_BY_GENDER.get(gender, _FALLBACK_BY_GENDER["unknown"])
        known_native = {"aiden", "dylan", "eric", "ono_anna", "ryan",
                        "serena", "sohee", "uncle_fu", "vivian"}
        if job.voice_id in known_native:
            return job.voice_id
        return pool[0]

    def synthesize(self, job: TTSJob, output_dir: Path | None = None) -> ChunkResult:
        import tempfile
        out_dir = output_dir or Path(tempfile.mkdtemp())
        out_dir.mkdir(parents=True, exist_ok=True)
        wav_path = out_dir / f"{job.job_id}.wav"

        # --- Silence jobs ---
        if job.voice_type == "silence" or not job.text.strip():
            _generate_silent_wav(0.8, wav_path)
            return ChunkResult(
                job_id=job.job_id, wav_path=str(wav_path), duration_ms=800,
                text=job.text, character=job.character, element_ids=job.element_ids,
                scene=job.scene, element_type=job.element_type,
            )

        # Determine speaker
        if job.voice_type == "native" and job.voice_id in {
            "aiden", "dylan", "eric", "ono_anna", "ryan",
            "serena", "sohee", "uncle_fu", "vivian"
        }:
            speaker = job.voice_id
        else:
            speaker = self._fallback_speaker(job)

        # Prepare HTTP Payload
        payload = {
            "text": job.text,
            "voice_type": job.voice_type,
            "speaker": speaker,
            "instruct": job.instruct or ""
        }

        req = urllib.request.Request(
            f"{self.server_url}/synthesize",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

        generated = False
        try:
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    wav_path.write_bytes(response.read())
                    generated = True
                else:
                    print(f"TTS Server returned HTTP {response.status}")
        except Exception as e:
            print(f"Failed to connect to TTS server at {self.server_url}: {e}")

        # Silent placeholder fallback if request failed
        if not generated:
            est_dur = max(len(job.text) / 15.0, 0.5)
            _generate_silent_wav(est_dur, wav_path)

        _postprocess(wav_path)

        return ChunkResult(
            job_id=job.job_id, wav_path=str(wav_path), duration_ms=_wav_duration_ms(wav_path),
            text=job.text, character=job.character, element_ids=job.element_ids,
            scene=job.scene, element_type=job.element_type,
        )