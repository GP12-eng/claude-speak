# ClaudeSpeak (克言) — Full-Duplex Voice Programming Assistant

Talk to Claude Code. Naturally. Like a phone call.

A full-duplex voice interface that lets developers speak to Claude Code instead of typing. Floating desktop ball, wake word activation, real-time STT/TTS, barge-in support, VSCode deep integration, and mobile PWA remote access.

**Phase 1 in progress. Hub + Audio + STT + TTS + VSCode bridge written. 1 person + Claude Code.**

## The Problem

Typing is the bottleneck in AI-assisted development. Chinese input method switching, long-form expression, and the gap between what you think and what you can type — all friction. Voice output is 3-5x faster than typing for complex ideas.

## What It Does

- **Full-duplex conversation**: Talk and listen simultaneously — like a real conversation, not walkie-talkie
- **Barge-in**: Interrupt Claude while it's speaking. Just start talking
- **Floating ball UI**: Lives on your desktop. Decibel ring shows your voice level. Glows when listening
- **Wake word**: "Hey Claude" activates it. No keyboard needed
- **VSCode deep integration**: Transcribed text goes directly to Claude Code terminal. Responses stream back as voice
- **Mobile remote**: Phone PWA connects to desktop Hub over WiFi. Take Claude Code with you

## Architecture

```
Desktop Hub (Python)          ← WebSocket →  Floating Ball (Electron)
  ├── Audio Capture + VAD                    VSCode Extension (TypeScript)
  ├── SenseVoice STT (Chinese CER ~3%)       Mobile PWA (Web Audio API)
  ├── Claude API Bridge
  └── Edge TTS + Piper Fallback
```

Hub-Spoke architecture. Desktop is the brain (all AI processing). Clients are pure presentation.

## Targets

| Metric | Goal |
|--------|------|
| E2E latency (speech → first audio) | < 1s |
| Barge-in recovery | < 300ms |
| Chinese STT accuracy (CER) | ~3% (SenseVoice-Small) |
| Continuous conversation | 30+ min no crash |

## Tech Stack

| Component | Choice |
|-----------|--------|
| STT | SenseVoice-Small (234M, CPU) |
| STT Fallback | faster-whisper medium |
| LLM | Claude API via VSCode Claude Code extension |
| TTS | Edge TTS (Chinese neural voices) |
| TTS Fallback | Piper-TTS (local) |
| Wake Word | openWakeWord (Phase 2) |
| VAD | Silero VAD (ONNX) |
| Floating Ball | Electron (Phase 2) |
| Audio I/O | sounddevice |
| Hub IPC | WebSocket (typed JSON + binary frames) |

## Project Structure

```
voice_claude_hub/
  main.py              # Entry point: wires Hub + Audio + STT + Claude + TTS
  config.py            # .env loader + device discovery
  models.py            # Pydantic WebSocket message types
  session_manager.py   # State machine (IDLE→LISTENING→THINKING→SPEAKING) + SQLite history
  ws_server.py         # WebSocket server + client registry + message dispatch
  audio_engine.py      # sounddevice mic capture + Silero VAD + decibel meter
  stt_engine.py        # faster-whisper medium (SenseVoice-Small when network allows)
  tts_engine.py        # edge-tts + Piper-TTS fallback
vscode-voice-bridge/
  src/extension.ts     # VSCode extension: receives text, runs `claude -p`, returns response
requirements.txt
.env.example
```

## Getting Started

```bash
# Install dependencies
pip install -r requirements.txt

# Set your API key
cp .env.example .env
# Edit .env → add ANTHROPIC_API_KEY

# Start the Hub
python -m voice_claude_hub.main
```

Hub starts on `ws://localhost:9877`. Press Ctrl+Shift+V to activate (Phase 1 — shortcut activation).

## Built by

**GPI** — Solo developer. 6 products in 10 days with Claude Code.

*"The engineering barrier is gone. What remains is taste."*
