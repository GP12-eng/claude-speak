"""Configuration from .env + device discovery."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


def _find_env() -> str | None:
    candidates = [
        Path(__file__).resolve().parent.parent / ".env",
        Path.cwd() / ".env",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


def load_config() -> None:
    env_path = _find_env()
    if env_path:
        load_dotenv(env_path)
    else:
        print("Warning: .env not found, using defaults")


def get(key: str, default: str = "") -> str:
    return os.getenv(key, default)


# --- Audio ---
SAMPLE_RATE: int = int(get("SAMPLE_RATE", "16000"))
AUDIO_INPUT_DEVICE: str | int = int(get("AUDIO_INPUT_DEVICE", "0") or "0")  # 0 = system default input
AUDIO_OUTPUT_DEVICE: str | int = int(get("AUDIO_OUTPUT_DEVICE", "0") or "0")  # 0 = system default output
VAD_SILENCE_MS: int = int(get("VAD_SILENCE_MS", "800"))

# --- AI ---
LLM_PROVIDER: str = get("LLM_PROVIDER", "deepseek")  # deepseek | anthropic
DEEPSEEK_API_KEY: str = get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL: str = get("DEEPSEEK_MODEL", "deepseek-chat")
ANTHROPIC_API_KEY: str = get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL: str = get("CLAUDE_MODEL", "claude-sonnet-4-6")
SYSTEM_PROMPT: str = get("SYSTEM_PROMPT", "你是一个友好的语音编程助手，回复简洁有力。用中文回答。")
STT_MODEL: str = get("STT_MODEL", "faster-whisper")
MAX_HISTORY_TURNS: int = int(get("MAX_HISTORY_TURNS", "20"))

# --- Network ---
HUB_PORT: int = int(get("HUB_PORT", "9877"))

# Load on import
load_config()
