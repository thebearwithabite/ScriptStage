"""TTS synthesis engine — VoiceDesign primary, CustomVoice fallback."""

from __future__ import annotations

import traceback
import wave
from pathlib import Path
from typing import Optional

from core.models import ChunkResult, TTSJob

SAMPLE_RATE = 24000

# Local model paths
CUSTOM_VOICE_PATH = "~/models/Qwen3-TTS-12Hz-1.7B-CustomVoice"
VOICE_DESIGN_PATH = "~/models/models--Qwen--Qwen3-TTS-12Hz-1.7B-VoiceDesign/snapshots/5ecdb67327fd37bb2e042aab12ff7391903235d3"

# Fallback native speaker pool per gender (used when VD fails)
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
    """Synthesizes audio chunks. VoiceDesign is primary; CustomVoice is fallback."""

    def __init__(
        self,
        model_dir: Optional[str] = None,
        vd_model_dir: Optional[str] = None,
    ) -> None:
        self._model = None       # CustomVoice (fallback)
        self._model_vd = None    # VoiceDesign (primary)
        self._model_dir = model_dir
        self._vd_model_dir = vd_model_dir
        self._load_error: Optional[str] = None
        self._load_error_vd: Optional[str] = None
        self._load_models()

    def _load_models(self) -> None:
        # ── VoiceDesign (primary) ─────────────────────────────────────────
        try:
            from qwen_tts import Qwen3TTSModel
            vd_path = str(Path(self._vd_model_dir or VOICE_DESIGN_PATH).expanduser())
            self._model_vd = Qwen3TTSModel.from_pretrained(
                vd_path, device_map="auto"
            )
        except Exception as e:
            self._model_vd = None
            self._load_error_vd = str(e)

        # ── CustomVoice (fallback) ────────────────────────────────────────
        try:
            from qwen_tts import Qwen3TTSModel
            cv_path = str(Path(self._model_dir or CUSTOM_VOICE_PATH).expanduser())
            self._model = Qwen3TTSModel.from_pretrained(
                cv_path, device_map="auto"
            )
        except Exception as e:
            self._model = None
            self._load_error = str(e)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _synth_voice_design(self, text: str, instruct: str, wav_path: Path) -> bool:
        """Call VoiceDesign model. Returns True on success."""
        if not self._model_vd or not instruct.strip():
            return False
        try:
            import soundfile as sf
            result = self._model_vd.generate_voice_design(
                text=text,
                instruct=instruct,
                language="english",
            )
            audio_list, sr = result
            sf.write(str(wav_path), audio_list[0], sr)
            return True
        except Exception:
            self._last_vd_error = traceback.format_exc()
            return False

    def _synth_custom_voice(
        self, text: str, speaker: str, instruct: str, wav_path: Path
    ) -> bool:
        """Call CustomVoice model. Returns True on success."""
        if not self._model:
            return False
        try:
            import soundfile as sf
            result = self._model.generate_custom_voice(
                text=text,
                speaker=speaker,
                language="english",
                instruct=instruct or None,
            )
            audio_list, sr = result
            sf.write(str(wav_path), audio_list[0], sr)
            return True
        except Exception:
            self._last_cv_error = traceback.format_exc()
            return False

    def _fallback_speaker(self, job: TTSJob) -> str:
        """Pick the best native fallback speaker for a job."""
        gender = job.gender_hint if hasattr(job, "gender_hint") else "unknown"
        pool = _FALLBACK_BY_GENDER.get(gender, _FALLBACK_BY_GENDER["unknown"])
        # voice_id may carry a slug like "vd_monroe" or a real native id
        # If voice_id is already a known native speaker, prefer it
        known_native = {"aiden", "dylan", "eric", "ono_anna", "ryan",
                        "serena", "sohee", "uncle_fu", "vivian"}
        if job.voice_id in known_native:
            return job.voice_id
        return pool[0]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def synthesize(self, job: TTSJob, output_dir: Path | None = None) -> ChunkResult:
        """Generate audio for a single TTS job.

        Priority:
          1. VoiceDesign with job.instruct (all character/narrator lines)
          2. CustomVoice with gender-appropriate fallback speaker
          3. Silent placeholder
        """
        import tempfile
        out_dir = output_dir or Path(tempfile.mkdtemp())
        out_dir.mkdir(parents=True, exist_ok=True)
        wav_path = out_dir / f"{job.job_id}.wav"

        # --- Silence jobs ---
        if job.voice_type == "silence" or not job.text.strip():
            _generate_silent_wav(0.8, wav_path)
            return ChunkResult(
                job_id=job.job_id,
                wav_path=str(wav_path),
                duration_ms=800,
                text=job.text,
                character=job.character,
                element_ids=job.element_ids,
                scene=job.scene,
                element_type=job.element_type,
            )

        generated = False

        # 1. VoiceDesign (primary — all voice types with an instruct)
        if job.instruct and job.instruct.strip():
            generated = self._synth_voice_design(job.text, job.instruct, wav_path)

        # 2. CustomVoice fallback
        if not generated:
            # For native jobs use voice_id as speaker; for VD jobs pick by gender
            if job.voice_type == "native" and job.voice_id in {
                "aiden", "dylan", "eric", "ono_anna", "ryan",
                "serena", "sohee", "uncle_fu", "vivian"
            }:
                speaker = job.voice_id
            else:
                speaker = self._fallback_speaker(job)
            generated = self._synth_custom_voice(
                job.text, speaker, job.instruct, wav_path
            )

        # 3. Silent placeholder
        if not generated:
            est_dur = max(len(job.text) / 15.0, 0.5)
            _generate_silent_wav(est_dur, wav_path)

        _postprocess(wav_path)

        return ChunkResult(
            job_id=job.job_id,
            wav_path=str(wav_path),
            duration_ms=_wav_duration_ms(wav_path),
            text=job.text,
            character=job.character,
            element_ids=job.element_ids,
            scene=job.scene,
            element_type=job.element_type,
        )
