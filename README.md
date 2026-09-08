# PipeWire Agent Screen Capture Skill

A specialized skill for Linux systems (KDE Plasma, GNOME, and Wayland/X11 compositors) that enables AI agents to interactively request screen or application window captures from the user via **XDG Desktop Portal** and **PipeWire**.

---

## Global Availability Across All AI Agents

This tool is installed globally on your system and is accessible to **all** agents:

Agent Ecosystem | Integration Location | How the Agent Uses It
:--- | :--- | :---
**Antigravity** | `~/.gemini/config/skills/pipewire-screen-capture` + `~/.gemini/config/skills.json` | Automatically activates the `pipewire-screen-capture` skill across any workspace.
**Claude Code** | `~/.claude/skills/pipewire-screen-capture` + `~/.claude/CLAUDE.md` | Discovered in Claude Code skills and referenced in global instructions.
**Any CLI Agent** *(Aider, OpenCode, Cursor, Gaia, Copilot, Terminal)* | `~/.local/bin/agent-screen-capture` *(in system `$PATH`)* | Runs `agent-screen-capture --reason "..."` from any directory.
**Standard Agents** | `~/.agents/skills/pipewire-screen-capture` | Standard user-level agent skill discovery.

---

## The Workflow

```text
[Agent Formulates Reason]
           │
           ▼
[Desktop Notification ("notify-send")]
           │
           ▼
[KDE Plasma / GNOME ScreenCast Portal Dialog]
           │
   ┌───────┴───────┐
   ▼               ▼
[User Cancels]   [User Selects Window/Screen & Clicks "Share"]
   │               │
   ▼               ▼
(Exit code 1)    [PipeWire Stream -> GStreamer appsink -> PNG Image]
                   │
                   ▼
                 [Agent views image via view_file / embeds in Artifact]
```

1. **Say what you are looking for**: The agent specifies a `--reason` explaining what it is inspecting (e.g., verifying a GUI app layout, examining an error modal, or checking graphical rendering). The reason is printed to stderr and shown in a desktop notification via `notify-send`.
2. **KDE or GNOME request pops up**: The script initiates an `org.freedesktop.portal.ScreenCast` session via D-Bus, prompting the desktop environment's native dialog where the user selects either a single application window or an entire monitor.
3. **User clicks Share**: Once granted, the script receives the PipeWire stream node, connects via GStreamer (`pipewiresrc`), captures a pristine frame into memory, saves it as a high-quality PNG, and cleanly closes the session (dismissing the screen share indicator). The agent can immediately view the captured image with `view_file` or embed it in an artifact.

---

## Global Installation

Run the universal installer at any time:

```bash
./install.sh
```

The installer configures:
1. `~/.local/bin/agent-screen-capture` (in `$PATH`)
2. `~/.gemini/config/skills/pipewire-screen-capture` (for Antigravity)
3. `~/.gemini/config/skills.json` (Antigravity global registry)
4. `~/.claude/skills/pipewire-screen-capture` & `~/.claude/CLAUDE.md` (for Claude Code)
5. `~/.agents/skills/pipewire-screen-capture` (standard multi-agent directory)

---

## CLI Usage (From Any Directory)

### Basic Capture
```bash
agent-screen-capture --reason "Checking GUI application layout"
```

### Specify Output Destination
```bash
agent-screen-capture \
  --reason "Inspecting settings dialog" \
  --output ./screenshots/settings_window.png
```

### JSON Output (For Automation / Agents)
```bash
agent-screen-capture \
  --reason "Automated layout test" \
  --json
```

Output:
```json
{
  "status": "success",
  "image_path": "/home/shane/screenshots/capture_20260908_144500.png",
  "width": 1920,
  "height": 1080,
  "size_bytes": 352140,
  "reason": "Automated layout test",
  "elapsed_seconds": 1.34
}
```

### CLI Options

Option | Type | Default | Description
:--- | :--- | :--- | :---
`--reason`, `-r` | `string` | *(Required)* | Reason for screen capture; shown in notification and terminal.
`--output`, `-o` | `string` | `./screenshots/capture_<timestamp>.png` | Filepath where the screenshot should be saved.
`--source-type`, `-s` | `all`, `monitor`, `window` | `all` | Filter allowed sources in the KDE/GNOME dialog.
`--no-cursor` | flag | `False` | Hide mouse cursor in the screenshot.
`--delay`, `-d` | `float` | `0.0` | Seconds to wait before grabbing the frame after the user clicks Share.
`--timeout`, `-t` | `int` | `60` | Maximum seconds to wait for user to confirm the dialog.
`--no-notify` | flag | `False` | Suppress desktop notification.
`--debug` | flag | `False` | Print detailed D-Bus and GStreamer diagnostic logs to stderr.
`--json` | flag | `False` | Output structured JSON.

---

## Exit Codes

Exit Code | Meaning
:---: | :---
`0` | Success (frame captured and saved)
`1` | User cancelled or denied the portal request
`2` | Request timed out waiting for user confirmation
`3` | System error (D-Bus, PipeWire, GStreamer, or I/O failure)

---

## License

MIT License.
