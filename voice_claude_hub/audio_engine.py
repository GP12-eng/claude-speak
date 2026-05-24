"""Audio capture with Silero VAD and decibel metering. Runs in dedicated thread."""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)

# Frames: 30ms at 16kHz = 480 samples (must match Silero VAD requirement)
FRAME_MS = 30


class AudioEngine:
    def __init__(
        self,
        sample_rate: int = 16000,
        device: str | int = "default",
        silence_ms: int = 800,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        # sounddevice accepts int index or string name
        try:
            self.device: int | str = int(device) if isinstance(device, str) and device.isdigit() else device
        except ValueError:
            self.device = device
        self.silence_frames = silence_ms // FRAME_MS
        self._loop = loop or asyncio.get_event_loop()

        # state
        self._stream: sd.InputStream | None = None
        self._running = False
        self._vad_model: Any = None

        # audio buffer — accumulates frames during a speech segment
        self._audio_buffer: list[np.ndarray] = []
        self._silence_counter = 0
        self._is_speaking = False

        # decibel ring buffer (50ms updates, EMA smoothed)
        self._db_buffer: deque[float] = deque(maxlen=5)
        self._db_smoothed = 0.0

        # callbacks (set by session manager)
        self.on_speech_start: asyncio.coroutine | None = None
        self.on_speech_end: asyncio.coroutine | None = None
        self.on_decibel: asyncio.coroutine | None = None
        self.on_barge_in: asyncio.coroutine | None = None

    def compute_rms_db(self, chunk: np.ndarray) -> float:
        rms = np.sqrt(np.mean(chunk.astype(np.float64) ** 2))
        if rms < 1e-10:
            return 0.0
        db = 20.0 * np.log10(rms / 32768.0)
        return float(max(0.0, min(1.0, (db + 60.0) / 60.0)))

    def _audio_callback(self, indata: np.ndarray, frames: int, _time_info, _status) -> None:
        if not self._running:
            return

        chunk = indata[:, 0].copy() if indata.ndim > 1 else indata.copy()

        # decibel
        level = self.compute_rms_db(chunk)
        self._db_smoothed = self._db_smoothed * 0.7 + level * 0.3
        self._loop.call_soon_threadsafe(
            lambda l=self._db_smoothed: asyncio.ensure_future(
                self._on_decibel_safe(l)
            )
        )

        # VAD
        is_speech = self._vad_detect(chunk) if self._vad_model else self._energy_detect(chunk)

        if is_speech and not self._is_speaking:
            self._is_speaking = True
            self._silence_counter = 0
            self._audio_buffer = [chunk]
            self._loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(self._on_speech_start_safe())
            )
        elif is_speech and self._is_speaking:
            self._silence_counter = 0
            self._audio_buffer.append(chunk)
        elif not is_speech and self._is_speaking:
            self._silence_counter += 1
            self._audio_buffer.append(chunk)
            if self._silence_counter >= self.silence_frames:
                audio_data = np.concatenate(self._audio_buffer)
                self._is_speaking = False
                self._audio_buffer = []
                self._loop.call_soon_threadsafe(
                    lambda d=audio_data: asyncio.ensure_future(
                        self._on_speech_end_safe(d)
                    )
                )

    async def _on_decibel_safe(self, level: float) -> None:
        if self.on_decibel:
            await self.on_decibel(level)

    async def _on_speech_start_safe(self) -> None:
        logger.info("Speech started")
        if self.on_speech_start:
            await self.on_speech_start()

    async def _on_speech_end_safe(self, audio_data: np.ndarray) -> None:
        logger.info("Speech ended — %d samples", len(audio_data))
        if self.on_speech_end:
            await self.on_speech_end(audio_data)

    def _energy_detect(self, chunk: np.ndarray) -> bool:
        """Fallback energy-based VAD when Silero not loaded."""
        rms = np.sqrt(np.mean(chunk.astype(np.float64) ** 2))
        return rms > 500  # threshold for 16-bit audio

    def _vad_detect(self, chunk: np.ndarray) -> bool:
        if self._vad_model is None:
            return self._energy_detect(chunk)
        # Silero VAD: expects float32 [-1, 1], returns 0-1
        audio_float = chunk.astype(np.float32) / 32768.0
        prob = self._vad_model(audio_float, self.sample_rate).item()
        return prob > 0.5

    async def load_vad(self) -> None:
        try:
            import torch

            model, _ = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                force_reload=False,
            )
            self._vad_model = model
            logger.info("Silero VAD loaded")
        except Exception:
            logger.warning("Silero VAD unavailable, using energy-based fallback")

    async def start(self) -> None:
        await self.load_vad()
        self._running = True
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            device=self.device,
            channels=1,
            dtype="int16",
            blocksize=int(self.sample_rate * FRAME_MS / 1000),
            callback=self._audio_callback,
        )
        self._stream.start()
        logger.info("Audio engine started")

    async def stop(self) -> None:
        self._running = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        logger.info("Audio engine stopped")
