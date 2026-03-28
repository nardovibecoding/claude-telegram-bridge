#!/usr/bin/env bash
# Claude Telegram Bridge — one-liner installer
# curl -fsSL https://raw.githubusercontent.com/nardovibecoding/claude-telegram-bridge/main/install.sh | bash
set -euo pipefail

INSTALL_DIR="$HOME/claude-telegram-bridge"

RED='\033[0;31m' GREEN='\033[0;32m' YELLOW='\033[1;33m' CYAN='\033[0;36m' BOLD='\033[1m' NC='\033[0m'

echo ""
echo -e "${CYAN}${BOLD}"
echo "  ╔══════════════════════════════════════╗"
echo "  ║   Claude Telegram Bridge Installer    ║"
echo "  ║   Full Claude Code access via Telegram ║"
echo "  ╚══════════════════════════════════════╝"
echo -e "${NC}"

# --- Check prerequisites ---
MISSING=""
command -v python3 &>/dev/null || MISSING="$MISSING python3"
command -v claude &>/dev/null || MISSING="$MISSING claude-cli"

if [ -n "$MISSING" ]; then
  echo -e "${RED}✗ Missing prerequisites:$MISSING${NC}"
  echo -e "  Install Python 3.10+ and Claude Code CLI first."
  echo -e "  Claude Code: ${CYAN}https://claude.ai/claude-code${NC}"
  exit 1
fi

# --- Clone or update ---
if [ -d "$INSTALL_DIR/.git" ]; then
  echo -e "${YELLOW}→ Updating existing install...${NC}"
  git -C "$INSTALL_DIR" pull --ff-only 2>/dev/null || true
else
  if [ -d "$INSTALL_DIR" ]; then
    echo -e "${RED}✗ $INSTALL_DIR exists but is not a git repo. Remove it first.${NC}"
    exit 1
  fi
  echo -e "${GREEN}→ Cloning repository...${NC}"
  git clone https://github.com/nardovibecoding/claude-telegram-bridge.git "$INSTALL_DIR"
fi

# --- Install dependencies ---
echo -e "${GREEN}→ Installing Python dependencies...${NC}"
pip3 install --quiet python-telegram-bot claude-agent-sdk 2>/dev/null || {
  pip install --quiet python-telegram-bot claude-agent-sdk 2>/dev/null || {
    echo -e "${RED}✗ Failed to install dependencies. Run manually: pip install -r $INSTALL_DIR/requirements.txt${NC}"
  }
}

# --- Configure ---
echo ""
echo -e "${BOLD}Configuration${NC}"
echo ""

# Bot token
read -rp "Telegram bot token (from @BotFather): " BOT_TOKEN
if [ -z "$BOT_TOKEN" ]; then
  echo -e "${RED}✗ Bot token is required.${NC}"
  exit 1
fi

# Allowed users
echo -e "${YELLOW}  Tip: find your Telegram user ID by messaging @userinfobot${NC}"
read -rp "Allowed user IDs (comma-separated, blank = all): " ALLOWED_USERS

# Model
echo ""
echo -e "  Models: ${CYAN}haiku${NC} (fast) | ${CYAN}sonnet${NC} (balanced) | ${CYAN}opus${NC} (powerful)"
read -rp "Default model [sonnet]: " MODEL
MODEL=${MODEL:-sonnet}

# Working directory
read -rp "Working directory [~]: " WORKING_DIR
WORKING_DIR=${WORKING_DIR:-~}

# --- Write .env ---
cat > "$INSTALL_DIR/.env" << ENVEOF
BOT_TOKEN=$BOT_TOKEN
ALLOWED_USERS=$ALLOWED_USERS
MODEL=$MODEL
WORKING_DIR=$WORKING_DIR
ENVEOF
echo -e "${GREEN}→ Saved .env${NC}"

# --- Done ---
echo ""
echo -e "${GREEN}${BOLD}✓ Claude Telegram Bridge installed!${NC}"
echo ""
echo -e "  To start the bot:"
echo -e "    ${CYAN}cd ~/claude-telegram-bridge && python3 bot.py${NC}"
echo ""
echo -e "  To run in background:"
echo -e "    ${CYAN}nohup python3 ~/claude-telegram-bridge/bot.py &${NC}"
echo ""
echo -e "  Features: text, photos, documents, /cancel, rate limiting"
echo -e "  Full Claude Code tool access via Telegram."
echo ""
