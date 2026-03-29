<p align="center">
  <h1 align="center">claude-telegram-bridge</h1>
  <p align="center"><strong>Control Claude Code from Telegram — full tool access, streaming responses, from any device.</strong></p>
</p>

<p align="center">
  <a href="https://github.com/nardovibecoding/claude-telegram-bridge/stargazers">
    <img src="https://img.shields.io/github/stars/nardovibecoding/claude-telegram-bridge?style=for-the-badge&color=orange" alt="Stars">
  </a>
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Platform-macOS%20%7C%20Linux-lightgrey?style=for-the-badge" alt="Platform">
  <img src="https://img.shields.io/badge/Model-Haiku%20%7C%20Sonnet%20%7C%20Opus-purple?style=for-the-badge" alt="Models">
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/License-AGPL--3.0-red?style=for-the-badge" alt="License">
  </a>
</p>

<p align="center">
  <img src="demo.gif" alt="Telegram bridge receiving command and streaming Claude Code response" width="700">
</p>

---

You're away from your Mac. An idea hits, or someone needs something urgently. You want Claude to just handle it — search the web, read a file, write code — without opening a terminal.

## Install

One command. Takes 60 seconds.

```bash
curl -fsSL https://raw.githubusercontent.com/nardovibecoding/claude-telegram-bridge/main/install.sh | bash
```

Clones the repo, installs dependencies, prompts for bot token + settings, writes `.env`. Just run `python3 bot.py` after.

**Prerequisites:**
- Python 3.10+
- [Claude Code CLI](https://claude.ai/claude-code) installed and authenticated
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))

---

## Quickstart

```bash
export BOT_TOKEN="your_telegram_bot_token"
export ALLOWED_USERS="123456789"   # your Telegram user ID
export WORKING_DIR="/path/to/project"
export MODEL="sonnet"              # haiku | sonnet | opus

python bot.py
```

Then open your bot in Telegram and start messaging:

```
You:  What's the git status?

Bot:  Working...
        $ git status
        Read README.md

Bot:  Clean — on branch main, 3 commits ahead of origin.
      Last commit: "fix: handle edge case in parser"
      (4.2s, 2 tool calls)
```

---

## How It Works

```
Telegram message
      │
      ▼
  Bot (bot.py)
      │   auth check → allowed users only
      │
      ▼
Claude Code SDK (sdk_client.py)
      │   persistent connection, auto-reconnect
      │
      ├──▶ Bash      $ git status, pytest, npm run build …
      ├──▶ Read      open any file in the working directory
      ├──▶ Write     create new files
      ├──▶ Edit      patch existing files
      ├──▶ Grep      search file contents
      ├──▶ Glob      find files by pattern
      ├──▶ WebSearch research from the web
      ├──▶ WebFetch  fetch a URL
      └──▶ Agent     spawn sub-agents for complex tasks
             │
             ▼
      streaming response
      (tool calls shown live as they happen)
             │
             ▼
      Telegram reply with timing stats
```

Cold start: ~6 s once. Subsequent messages: 2–3 s.

---

## Features

| Capability | Detail |
|---|---|
| Full tool access | Bash, Read, Write, Edit, Grep, Glob, WebSearch, WebFetch, Agent |
| Live tool progress | Each tool call shown in real-time as Claude works |
| Streaming text | Response text updates as it arrives, not just at the end |
| Long message splitting | Responses >4096 chars split automatically |
| Task cancellation | `/cancel` stops a running task mid-execution |
| Auto-reconnect | Persistent SDK connection restarts transparently on crash |
| Multi-model | Switch between Haiku, Sonnet, and Opus via env var |
| Allowlist auth | Restrict access to specific Telegram user IDs |
| Custom working dir | Point Claude at any directory on the host machine |
| Custom system prompt | Override the default assistant persona |
| Markdown rendering | Bot responses rendered as HTML — bold, code, links preserved |
| Rate limiting | Configurable per-user message rate limit (default: 5 req/min) |
| File/image input | Send photos or documents — bot passes them to Claude as input |
| Multi-session | Per-chat working directories via JSON mapping |
| 3-file footprint | `bot.py` + `sdk_client.py` + `requirements.txt` — ~300 lines total |

---

## Setup Guide

### 1. Create a Telegram Bot

1. Open [@BotFather](https://t.me/BotFather) in Telegram
2. Send `/newbot` and follow the prompts
3. Copy the token — looks like `123456789:ABCdef...`

### 2. Find Your Telegram User ID

Message [@userinfobot](https://t.me/userinfobot) — it replies with your numeric user ID.

### 3. Configure Environment

```bash
export BOT_TOKEN="123456789:ABCdef..."    # from BotFather
export ALLOWED_USERS="111222333"          # your user ID (comma-separated for multiple)
export WORKING_DIR="$HOME/myproject"      # directory Claude operates in
export MODEL="sonnet"                     # haiku | sonnet | opus
export SYSTEM_PROMPT="You are a helpful coding assistant."  # optional
```

### 4. Run

```bash
python bot.py
```

To keep it running in the background:

```bash
nohup python bot.py > bridge.log 2>&1 &
```

Or as a systemd service (Linux):

```ini
[Unit]
Description=Claude Telegram Bridge

[Service]
ExecStart=/usr/bin/python3 /opt/claude-telegram-bridge/bot.py
EnvironmentFile=/opt/claude-telegram-bridge/.env
Restart=always

[Install]
WantedBy=multi-user.target
```

---

## Configuration Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `BOT_TOKEN` | Yes | — | Telegram bot token from BotFather |
| `ALLOWED_USERS` | No | (all users) | Comma-separated Telegram user IDs |
| `WORKING_DIR` | No | `~` | Directory Claude operates in |
| `MODEL` | No | `sonnet` | `haiku`, `sonnet`, or `opus` |
| `SYSTEM_PROMPT` | No | `"You are a helpful coding assistant."` | System prompt for the session |
| `RATE_LIMIT` | No | `5` | Max messages per user per minute |
| `CHAT_DIRS` | No | — | JSON mapping of chat ID → working dir, e.g. `{"123456": "/projects/foo"}` |

---

## Commands

| Command | What it does |
|---|---|
| (any text) | Sent to Claude Code — full tool access |
| `/cancel` | Cancel the currently running task |

---

## Security

**ALLOWED_USERS is your first line of defense.** Set it to your Telegram user ID. Without it, anyone who finds your bot can execute shell commands on your machine.

```bash
# Single user
export ALLOWED_USERS="111222333"

# Multiple users
export ALLOWED_USERS="111222333,444555666"
```

**What Claude can do:** The bot runs with `bypassPermissions` — Claude executes tools without confirmation prompts. This is intentional for speed, but means every allowed user has full shell access to the `WORKING_DIR`. Only grant access to users you trust completely.

**Credentials:** `BOT_TOKEN` and `ALLOWED_USERS` are env vars — never committed to git. Use a `.env` file locally and `EnvironmentFile` in systemd.

---

## Architecture

3 files, ~300 lines:

| File | Lines | Responsibility |
|---|---|---|
| `bot.py` | ~160 | Telegram bot — auth, message handling, progress display, cancellation |
| `sdk_client.py` | ~130 | Claude SDK wrapper — persistent connection, streaming, auto-reconnect |
| `requirements.txt` | 2 | `python-telegram-bot` + `claude-agent-sdk` |

The SDK client maintains a single persistent connection per process. On disconnect or crash, it reconnects transparently before the next query. The lock ensures concurrent Telegram messages are serialized to the same session.

---

## Battle-Tested

Extracted from a production multi-bot Telegram system running 8 AI personas with 2 000+ daily messages. The bridge pattern has been running continuously for months in real use.

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=nardovibecoding/claude-telegram-bridge&type=Date)](https://star-history.com/#nardovibecoding/claude-telegram-bridge&Date)

---

## License

[AGPL-3.0](LICENSE) — see [NOTICE](NOTICE) for attribution.
