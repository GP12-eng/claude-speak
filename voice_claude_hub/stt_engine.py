"""STT engine: faster-whisper (primary). SenseVoice via FunASR as future upgrade."""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# Use HF mirror for model downloads in China
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")


class STTEngine:
    def __init__(self, sample_rate: int = 16000) -> None:
        self.sample_rate = sample_rate
        self._model: Any = None
        self._model_type = ""

    async def load(self, model_type: str = "faster-whisper") -> None:
        self._model_type = model_type
        if model_type == "sensevoice":
            try:
                from funasr import AutoModel

                self._model = AutoModel(
                    model="iic/SenseVoiceSmall",
                    vad_model="fsmn-vad",
                    vad_kwargs={"max_single_segment_time": 30000},
                    trust_remote_code=True,
                )
                logger.info("SenseVoice-Small loaded")
            except Exception as e:
                logger.warning("SenseVoice failed: %s — falling back to faster-whisper", e)
                await self.load("faster-whisper")
        elif model_type == "faster-whisper":
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                "tiny",
                device="cpu",
                compute_type="int8",
            )
            logger.info("faster-whisper tiny loaded (switch to medium for better accuracy)")
        else:
            raise ValueError(f"Unknown STT model: {model_type}")

    async def transcribe(self, audio: np.ndarray) -> str:
        if self._model is None:
            raise RuntimeError("STT model not loaded")

        if self._model_type == "sensevoice":
            return await self._transcribe_sensevoice(audio)
        else:
            return await self._transcribe_whisper(audio)

    async def _transcribe_sensevoice(self, audio: np.ndarray) -> str:
        # SenseVoice expects a file path or numpy int16
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            import wave

            wav_path = f.name
        try:
            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(self.sample_rate)
                wf.writeframes(audio.tobytes())

            result = self._model.generate(input=wav_path)
            text = result[0]["text"] if result else ""
            # SenseVoice may include language tokens like "<|zh|>"
            text = text.replace("<|zh|>", "").replace("<|en|>", "").strip()
            return text
        finally:
            Path(wav_path).unlink(missing_ok=True)

    async def _transcribe_whisper(self, audio: np.ndarray) -> str:
        audio_float = audio.astype(np.float32) / 32768.0
        segments, _ = self._model.transcribe(audio_float, language="zh")
        return " ".join(seg.text for seg in segments).strip()
