"""State machine + barge-in coordinator + conversation history."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import HubState


@dataclass
class ConversationTurn:
    role: str  # "user" | "assistant"
    text: str
    ts: str = ""


@dataclass
class SessionState:
    state: HubState = HubState.IDLE
    pending_text: str = ""  # accumulating Claude stream
    interrupt_flag: bool = False
    stop_playback: bool = False

    # conversation
    history: deque[ConversationTurn] = field(default_factory=lambda: deque(maxlen=40))

    # metrics
    last_speech_start: float = 0.0
    last_speech_end: float = 0.0
    turn_count: int = 0

    def reset_for_new_turn(self) -> None:
        self.pending_text = ""
        self.interrupt_flag = False
        self.stop_playback = False

    def add_user_turn(self, text: str) -> None:
        self.history.append(ConversationTurn(role="user", text=text, ts=_now()))
        self.turn_count += 1

    def add_assistant_turn(self, text: str) -> None:
        self.history.append(ConversationTurn(role="assistant", text=text, ts=_now()))

    def build_messages(self, system_prompt: str, max_turns: int = 20) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        recent = list(self.history)[-max_turns * 2 :]
        for turn in recent:
            role = "user" if turn.role == "user" else "assistant"
            messages.append({"role": role, "content": turn.text})
        return messages


class ConversationStore:
    def __init__(self, db_path: str = "") -> None:
        if not db_path:
            db_path = str(Path(__file__).resolve().parent.parent / "conversations.db")
        self._db = sqlite3.connect(db_path)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS turns ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  session_id TEXT,"
            "  role TEXT,"
            "  text TEXT,"
            "  ts TEXT"
            ")"
        )
        self._db.commit()

    def save_turn(self, session_id: str, role: str, text: str) -> None:
        self._db.execute(
            "INSERT INTO turns (session_id, role, text, ts) VALUES (?, ?, ?, ?)",
            (session_id, role, text, _now()),
        )
        self._db.commit()

    def close(self) -> None:
        self._db.close()


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
