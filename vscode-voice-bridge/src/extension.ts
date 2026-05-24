import * as vscode from "vscode";
import WebSocket from "ws";

let ws: WebSocket | null = null;
let statusBar: vscode.StatusBarItem;

export function activate(context: vscode.ExtensionContext) {
  statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusBar.command = "claudespeak.connect";
  statusBar.text = "$(mic) ClaudeSpeak";
  statusBar.show();
  context.subscriptions.push(statusBar);

  const connectCmd = vscode.commands.registerCommand("claudespeak.connect", () => {
    connectToHub();
  });
  const disconnectCmd = vscode.commands.registerCommand("claudespeak.disconnect", () => {
    disconnect();
  });
  context.subscriptions.push(connectCmd, disconnectCmd);

  // Auto-connect if configured
  const hubUrl = vscode.workspace.getConfiguration("claudespeak").get<string>("hubUrl");
  if (hubUrl) {
    connectToHub();
  }
}

function connectToHub() {
  const hubUrl =
    vscode.workspace.getConfiguration("claudespeak").get<string>("hubUrl") ||
    "ws://localhost:9877";

  if (ws) {
    ws.close();
  }

  ws = new WebSocket(hubUrl);
  statusBar.text = "$(sync~spin) ClaudeSpeak connecting...";

  ws.on("open", () => {
    // Register as VSCode client
    ws!.send(
      JSON.stringify({
        type: "register",
        payload: { client_type: "vscode", client_id: "vscode" },
      })
    );
    statusBar.text = "$(mic) ClaudeSpeak";
    vscode.window.showInformationMessage("ClaudeSpeak connected");
  });

  ws.on("message", async (data) => {
    try {
      const msg = JSON.parse(data.toString());
      await handleMessage(msg);
    } catch {
      // binary audio frame, ignore in VSCode
    }
  });

  ws.on("close", () => {
    statusBar.text = "$(debug-disconnect) ClaudeSpeak";
    ws = null;
  });

  ws.on("error", (err) => {
    statusBar.text = "$(error) ClaudeSpeak";
    vscode.window.showErrorMessage(`ClaudeSpeak error: ${err.message}`);
  });
}

async function handleMessage(msg: { type: string; payload: any }) {
  switch (msg.type) {
    case "text.transcribed": {
      const text = msg.payload?.text;
      if (!text) return;

      // Send to Claude Code via one-shot `claude -p`
      const response = await sendToClaudeCode(text);
      if (response && ws) {
        ws.send(
          JSON.stringify({
            type: "text.response",
            payload: { text: response, is_streaming: false },
          })
        );
      }
      break;
    }
    case "state.change": {
      const state = msg.payload?.state;
      if (state === "LISTENING") {
        statusBar.text = "$(record) ClaudeSpeak";
      } else if (state === "THINKING") {
        statusBar.text = "$(loading~spin) ClaudeSpeak";
      } else if (state === "SPEAKING") {
        statusBar.text = "$(unmute) ClaudeSpeak";
      } else {
        statusBar.text = "$(mic) ClaudeSpeak";
      }
      break;
    }
  }
}

async function sendToClaudeCode(text: string): Promise<string> {
  try {
    const { execSync } = require("child_process");
    // Use `claude -p` for one-shot: clean input, clean output, no terminal noise
    const escaped = text.replace(/"/g, '\\"');
    const result = execSync(`claude -p "${escaped}"`, {
      encoding: "utf-8",
      timeout: 60000,
      maxBuffer: 1024 * 1024,
      env: { ...process.env, NO_COLOR: "1" },
    });
    return result.trim();
  } catch (err: any) {
    vscode.window.showErrorMessage(`Claude CLI failed: ${err.message}`);
    return "";
  }
}

function disconnect() {
  if (ws) {
    ws.close();
    ws = null;
  }
  statusBar.text = "$(debug-disconnect) ClaudeSpeak";
  vscode.window.showInformationMessage("ClaudeSpeak disconnected");
}

export function deactivate() {
  disconnect();
}
