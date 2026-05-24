"""TTS engine: edge-tts streaming + Piper-TTS fallback."""
from __future__ import annotations

import asyncio
import io
import logging
import tempfile
from pathlib import Path

import edge_tts
import sounddevice as sd

logger = logging.getLogger(__name__)

VOICE = "zh-CN-XiaoxiaoNeural"


class TTSEngine:
    def __init__(self, sample_rate: int = 16000, device: str = "default") -> None:
        self.sample_rate = sample_rate
        self.device = device
        self._use_edge = True
        self._piper_available = False

    async def check_piper(self) -> bool:
        try:
            import piper.voice

            self._piper_available = True
            return True
        except ImportError:
            logger.info("Piper-TTS not installed, edge-tts only")
            return False

    async def synthesize(self, text: str) -> io.BytesIO:
        if self._use_edge:
            try:
                return await self._edge_synthesize(text)
            except Exception as e:
                logger.warning("Edge TTS failed: %s", e)
                self._use_edge = False
        return await self._piper_synthesize(text)

    async def _edge_synthesize(self, text: str) -> io.BytesIO:
        communicate = edge_tts.Communicate(text, VOICE)
        buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        buf.seek(0)
        return buf

    async def _piper_synthesize(self, text: str) -> io.BytesIO:
        if not self._piper_available:
            raise RuntimeError("Piper-TTS not available and Edge TTS failed")
        import piper

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_path = f.name
        try:
            # Piper CLI mode
            import subprocess

            subprocess.run(
                ["piper", "--model", "zh_CN", "--output_file", wav_path],
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=30,
            )
            with open(wav_path, "rb") as f:
                return io.BytesIO(f.read())
        finally:
            Path(wav_path).unlink(missing_ok=True)

    async def play(self, audio: io.BytesIO) -> None:
        """Play MP3 audio via subprocess (Windows)."""
        import subprocess
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(audio.read())
            tmp_path = f.name

        try:
            # Windows: use mplay32 or direct show
            subprocess.run(
                ["cmd", "/c", "start", "/min", "wmplayer", tmp_path, "/play", "/close"],
                timeout=60,
            )
        except Exception:
            import os
            os.startfile(tmp_path)
        finally:
            # Cleanup after playback delay
            import time
            time.sleep(5)
            Path(tmp_path).unlink(missing_ok=True)

    async def fade_out_and_stop(self) -> None:
        """10ms linear fade-out for barge-in."""
        sd.stop()
