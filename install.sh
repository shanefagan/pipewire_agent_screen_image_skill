#!/usr/bin/env bash
#
# install.sh - Install PipeWire Screen Capture globally for all agents on the system:
#   1. Antigravity (global skills directory & skills.json)
#   2. Claude Code (~/.claude/skills/ and ~/.claude/CLAUDE.md)
#   3. Standard Agent Directory (~/.agents/skills/)
#   4. System-wide PATH for any CLI agent (~/.local/bin/agent-screen-capture)
#

set -euo pipefail

SKILL_NAME="pipewire-screen-capture"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${HOME}/.local/bin"

echo "=========================================================="
echo "Installing PipeWire Screen Capture Skill for All AI Agents"
echo "Source: ${SOURCE_DIR}"
echo "=========================================================="

# ---------------------------------------------------------
# 1. System CLI Binaries in ~/.local/bin ($PATH)
# ---------------------------------------------------------
mkdir -p "${BIN_DIR}"
echo "[1/4] Installing CLI tools to ${BIN_DIR}..."
ln -sfn "${SOURCE_DIR}/scripts/capture.sh" "${BIN_DIR}/pipewire-screen-capture"
ln -sfn "${SOURCE_DIR}/scripts/capture.sh" "${BIN_DIR}/agent-screen-capture"
chmod +x "${SOURCE_DIR}/scripts/capture.py" "${SOURCE_DIR}/scripts/capture.sh"
echo "      -> 'agent-screen-capture' and 'pipewire-screen-capture' are now in PATH."

# ---------------------------------------------------------
# 2. Antigravity Global Configuration
# ---------------------------------------------------------
GEMINI_SKILLS_DIR="${HOME}/.gemini/config/skills"
GEMINI_CONFIG_DIR="${HOME}/.gemini/config"
echo "[2/4] Registering skill with Antigravity..."
mkdir -p "${GEMINI_SKILLS_DIR}"
ln -sfn "${SOURCE_DIR}" "${GEMINI_SKILLS_DIR}/${SKILL_NAME}"

# Ensure global skills.json exists and registers ~/.gemini/config/skills
SKILLS_JSON="${GEMINI_CONFIG_DIR}/skills.json"
if [ ! -f "${SKILLS_JSON}" ]; then
    cat > "${SKILLS_JSON}" <<'EOF'
{
  "entries": [
    {
      "path": "~/.gemini/config/skills"
    }
  ]
}
EOF
    echo "      -> Created ${SKILLS_JSON}"
else
    echo "      -> ${SKILLS_JSON} exists."
fi

# ---------------------------------------------------------
# 3. Claude Code (~/.claude/skills)
# ---------------------------------------------------------
CLAUDE_DIR="${HOME}/.claude"
if [ -d "${CLAUDE_DIR}" ]; then
    echo "[3/4] Registering skill with Claude Code..."
    mkdir -p "${CLAUDE_DIR}/skills"
    ln -sfn "${SOURCE_DIR}" "${CLAUDE_DIR}/skills/${SKILL_NAME}"

    CLAUDE_MD="${CLAUDE_DIR}/CLAUDE.md"
    if ! grep -q "pipewire-screen-capture" "${CLAUDE_MD}" 2>/dev/null; then
        cat >> "${CLAUDE_MD}" <<'EOF'

# pipewire-screen-capture
- **pipewire-screen-capture** (`~/.claude/skills/pipewire-screen-capture/SKILL.md`): Request a screen or window capture from the user via PipeWire and XDG Desktop Portal using `agent-screen-capture --reason "..."`. Use whenever you need visual context of the screen, GUI apps, or error dialogs.
EOF
        echo "      -> Updated ${CLAUDE_MD}"
    else
        echo "      -> ${CLAUDE_MD} already configured."
    fi
else
    echo "[3/4] Skipping Claude Code (~/.claude not found)."
fi

# ---------------------------------------------------------
# 4. Standard Agent Workspace Directory (~/.agents/skills)
# ---------------------------------------------------------
AGENTS_DIR="${HOME}/.agents/skills"
echo "[4/4] Registering skill in standard ~/.agents/skills..."
mkdir -p "${AGENTS_DIR}"
ln -sfn "${SOURCE_DIR}" "${AGENTS_DIR}/${SKILL_NAME}"

echo ""
echo "Verifying prerequisites on this system:"
echo "----------------------------------------"
check_cmd() {
    if command -v "$1" >/dev/null 2>&1; then
        echo "  [OK] $1 found at $(command -v "$1")"
    else
        echo "  [WARNING] $1 not found in PATH"
    fi
}

check_cmd python3
check_cmd pw-cli
check_cmd gst-launch-1.0
check_cmd notify-send
check_cmd agent-screen-capture

python3 -c "import dbus, gi, PIL; gi.require_version('Gst', '1.0'); from gi.repository import Gst; Gst.init(None); print('  [OK] Python dependencies (dbus, gi/Gst, PIL) verified.')" 2>/dev/null || {
    echo "  [ERROR] Python modules (dbus, gi, PIL) check failed."
    exit 1
}

echo ""
echo "=========================================================="
echo "Installation complete!"
echo "Any agent on your system can now capture screenshots via:"
echo "  1. CLI in PATH:    agent-screen-capture --reason '...'"
echo "  2. Antigravity:    Activate 'pipewire-screen-capture' skill"
echo "  3. Claude Code:    Activate 'pipewire-screen-capture' skill"
echo "=========================================================="
