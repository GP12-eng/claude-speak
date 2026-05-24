"""Pydantic models for typed WebSocket messages."""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class HubState(StrEnum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"


class ClientType(StrEnum):
    BALL = "ball"
    VSCODE = "vscode"
    MOBILE = "mobile"


class Message(BaseModel):
    type: str
    payload: dict[str, Any] = {}
    ts: str = ""
    client_id: str = ""


# --- Client -> Hub ---

class WakeDetectedPayload(BaseModel):
    confidence: float
    word: str


class TextTranscribedPayload(BaseModel):
    text: str
    is_final: bool = True


class CommandPayload(BaseModel):
    action: str  # mute, pause, activate, deactivate
    params: dict[str, Any] = {}


# --- Hub -> Client ---

class StateChangePayload(BaseModel):
    state: HubState


class AudioPlayPayload(BaseModel):
    data: str  # base64-encoded MP3
    format: str = "mp3"


class TextResponsePayload(BaseModel):
    text: str
    is_streaming: bool = False


class DecibelLevelPayload(BaseModel):
    level: float  # 0.0 - 1.0
    source: str = "desktop"


class ErrorPayload(BaseModel):
    code: str
    message: str
