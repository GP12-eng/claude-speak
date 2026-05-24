"""ClaudeSpeak Hub — main entry point."""
from __future__ import annotations

import asyncio
import logging
import signal

import numpy as np

from .audio_engine import AudioEngine
from .config import (
    ANTHROPIC_API_KEY,
    AUDIO_INPUT_DEVICE,
    AUDIO_OUTPUT_DEVICE,
    CLAUDE_MODEL,
    DEEPSEEK_API_KEY,
    DEEPSEEK_MODEL,
    HUB_PORT,
    LLM_PROVIDER,
    MAX_HISTORY_TURNS,
    SAMPLE_RATE,
    SYSTEM_PROMPT,
    VAD_SILENCE_MS,
)
from .models import HubState
from .session_manager import ConversationStore, SessionState
from .stt_engine import STTEngine
from .tts_engine import TTSEngine
from .ws_server import HubServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("claudespeak")


# ---- LLM API calls ----

async def call_deepseek(messages: list[dict], api_key: str, model: str) -> str:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    response = await client.chat.completions.create(
        model=model,
        max_tokens=1024,
        messages=messages,
    )
    return response.choices[0].message.content or ""


async def call_claude(messages: list[dict], api_key: str, model: str) -> str:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=api_key)
    response = await client.messages.create(
        model=model,
        max_tokens=1024,
        messages=messages,
    )
    return response.content[0].text


async def call_llm(messages: list[dict]) -> str:
    if LLM_PROVIDER == "deepseek":
        return await call_deepseek(messages, DEEPSEEK_API_KEY, DEEPSEEK_MODEL)
    else:
        return await call_claude(messages, ANTHROPIC_API_KEY, CLAUDE_MODEL)


# ---- Main app ----

class ClaudeSpeakHub:
    def __init__(self) -> None:
        self.state = SessionState()
        self.store = ConversationStore()
        self.server = HubServer(port=HUB_PORT)
        self.audio = AudioEngine(
            sample_rate=SAMPLE_RATE,
            device=AUDIO_INPUT_DEVICE,
            silence_ms=VAD_SILENCE_MS,
        )
        self.stt = STTEngine(sample_rate=SAMPLE_RATE)
        self.tts = TTSEngine(sample_rate=SAMPLE_RATE, device=AUDIO_OUTPUT_DEVICE)

    async def setup(self) -> None:
        # Register WS handlers
        self.server.on("barge_in")(self._handle_barge_in)
        self.server.on("command")(self._handle_command)
        self.server.on("audio.chunk")(self._handle_mobile_audio)

        # Wire audio callbacks
        self.audio.on_speech_start = self._on_speech_start
        self.audio.on_speech_end = self._on_speech_end
        self.audio.on_decibel = self._on_decibel
        self.audio.on_barge_in = self._handle_barge_in

        # Load models
        await self.tts.check_piper()
        await self.stt.load()

    # ---- Audio callbacks ----

    async def _on_speech_start(self) -> None:
        if self.state.state == HubState.SPEAKING:
            # Barge-in!
            await self._handle_barge_in(None, {})
        self.state.state = HubState.LISTENING
        await self.server.registry.broadcast("state.change", {"state": self.state.state.value})

    async def _on_speech_end(self, audio_data: np.ndarray) -> None:
        if self.state.state != HubState.LISTENING:
            return

        self.state.state = HubState.THINKING
        await self.server.registry.broadcast("state.change", {"state": self.state.state.value})

        # STT
        try:
            text = await self.stt.transcribe(audio_data)
            if not text.strip():
                self.state.state = HubState.IDLE
                await self.server.registry.broadcast("state.change", {"state": HubState.IDLE.value})
                return
        except Exception as e:
            logger.error("STT failed: %s", e)
            await self.server.registry.broadcast("error", {"code": "STT_FAILED", "message": str(e)})
            self.state.state = HubState.IDLE
            return

        logger.info("Transcribed: %s", text)
        self.state.add_user_turn(text)

        # Try VSCode bridge first, fall back to direct Claude API
        response = ""
        vscode_connected = any(
            c.client_type.value == "vscode"
            for c in self.server.registry._clients.values()
        )

        if vscode_connected:
            # Send to VSCode bridge, wait for response
            await self.server.registry.broadcast("text.transcribed", {"text": text, "is_final": True})
            # VSCode will send back text.response — captured in WS handler below
            # For synchronous flow, use direct API as fallback while waiting
            # In Phase 1, we use direct API for reliability
            messages = self.state.build_messages(SYSTEM_PROMPT, MAX_HISTORY_TURNS)
            try:
                response = await call_llm(messages)
            except Exception as e:
                logger.error("Claude API failed: %s", e)
                await self.server.registry.broadcast("error", {"code": "LLM_FAILED", "message": str(e)})
                self.state.state = HubState.IDLE
                return
        else:
            messages = self.state.build_messages(SYSTEM_PROMPT, MAX_HISTORY_TURNS)
            try:
                response = await call_llm(messages)
            except Exception as e:
                logger.error("Claude API failed: %s", e)
                await self.server.registry.broadcast("error", {"code": "LLM_FAILED", "message": str(e)})
                self.state.state = HubState.IDLE
                return

        self.state.add_assistant_turn(response)
        await self.server.registry.broadcast("text.response", {"text": response, "is_streaming": False})

        # TTS
        self.state.state = HubState.SPEAKING
        await self.server.registry.broadcast("state.change", {"state": HubState.SPEAKING.value})

        try:
            audio = await self.tts.synthesize(response)
            await self.tts.play(audio)
        except Exception as e:
            logger.error("TTS failed: %s", e)

        self.state.state = HubState.IDLE
        self.state.reset_for_new_turn()
        await self.server.registry.broadcast("state.change", {"state": HubState.IDLE.value})

    async def _on_decibel(self, level: float) -> None:
        await self.server.registry.broadcast("decibel.level", {"level": level, "source": "desktop"})

    # ---- WS handlers ----

    async def _handle_barge_in(self, client_id: str | None, payload: dict) -> None:
        logger.info("Barge-in from %s", client_id)
        self.state.interrupt_flag = True
        self.state.stop_playback = True
        self.state.pending_text = ""
        await self.tts.fade_out_and_stop()
        self.state.state = HubState.LISTENING
        self.state.reset_for_new_turn()

    async def _handle_command(self, client_id: str, payload: dict) -> None:
        action = payload.get("action", "")
        logger.info("Command from %s: %s", client_id, action)

    async def _handle_mobile_audio(self, client_id: str, payload: dict) -> None:
        # Phase 4: receive raw PCM from mobile
        pass

    # ---- Lifecycle ----

    async def start(self) -> None:
        await self.setup()
        await self.audio.start()

        logger.info("=" * 40)
        logger.info("ClaudeSpeak Hub running on ws://0.0.0.0:%d", HUB_PORT)
        logger.info("Press Ctrl+Shift+V to activate (or send 'command' via WS)")
        logger.info("=" * 40)

        # Block until shutdown
        stop = asyncio.Event()
        loop = asyncio.get_event_loop()
        loop.add_signal_handler(signal.SIGINT, stop.set)
        loop.add_signal_handler(signal.SIGTERM, stop.set)

        await stop.wait()
        await self.shutdown()

    async def shutdown(self) -> None:
        logger.info("Shutting down...")
        self.state.state = HubState.IDLE
        await self.audio.stop()
        self.store.close()
        logger.info("Goodbye.")


def main() -> None:
    hub = ClaudeSpeakHub()
    asyncio.run(hub.start())


if __name__ == "__main__":
    main()
