---
name: voice-bridge-obsidian
description: >
  Process voice messages from Telegram or WhatsApp via a local bridge service.
  Transcribes audio via local STT, then Claude Code handles intent classification
  and metadata extraction natively (no API key needed), and archives everything
  into an Obsidian vault with structured frontmatter. Also generates daily and
  weekly digests. Use this skill whenever the user mentions voice messages,
  voice notes, audio transcription, Telegram voice, WhatsApp voice,
  voice-to-Obsidian, voice inbox processing, or wants to process audio recordings
  into structured notes. Also trigger when the user asks about daily/weekly
  digests of voice notes, or wants to set up voice-driven note capture workflows.
---

# Voice Bridge Obsidian

Pipeline: **Bridge → Event JSON → Script (STT) → Claude (Intent + Metadata) → Script (Write Obsidian)**

Claude Code itself handles intent classification and metadata extraction — no external API key needed.
Scripts only do what Claude can't: audio transcription and file I/O.

## When to Use This Skill

- A voice message event JSON arrives from a bridge service (Telegram / WhatsApp)
- The user asks to process, transcribe, or archive a voice recording
- The user wants to generate daily or weekly digests from voice notes
- The user asks to configure, test, or debug the voice-to-Obsidian pipeline

## Pre-Processing Checklist

Before running any script, verify:

1. **Config exists** — `config/settings.yaml` is present and valid (copy from `settings.example.yaml`)
2. **Vault path** — The configured Obsidian vault directory exists and is writable
3. **Audio file** — The `audio_path` in the event JSON points to an existing file
4. **STT backend** — The configured STT adapter (default: faster-whisper) is installed
5. **Log directory** — `logs/` exists and is writable
6. **Python** — Python 3.10+ is available

## Processing Flow

### Step 1: Validate + Transcribe (Script)

Claude calls the transcription script to validate the event and transcribe audio:

```bash
python3 scripts/transcribe_audio.py --event path/to/event.json
```

Output (JSON on stdout):
```json
{
  "transcript": "full text",
  "detected_language": "de",
  "confidence": 0.92,
  "segments": [{"start": 0.0, "end": 3.5, "text": "..."}]
}
```

If the event JSON has missing fields, the script exits with a clear error message.
STT backend is pluggable: `faster-whisper` (default), `whisper`, or custom adapter.

### Step 2: Intent Classification + Metadata Extraction (Claude)

**This is Claude's job — no API key needed, because you ARE Claude.**

After receiving the transcript, Claude classifies intent and extracts metadata directly.

**Intent categories:**
- `capture_idea` — spontaneous thoughts, 灵感
- `task` — to-do items, action items
- `journal` — mood, reflection, diary entries
- `project_update` — project progress reports
- `meeting_note` — meeting-related content
- `knowledge` — learning notes, excerpts
- `reminder_request` — time-based reminders
- `command_request` — system action requests
- `unknown` — cannot classify

**Metadata to extract:**
- `title` — concise title for the note
- `summary` — 1-2 sentence cleaned summary
- `keywords` — important terms (max 10)
- `entities` — people, projects, dates mentioned
- `project` — project name if identifiable (null otherwise)
- `action_items` — extractable to-do items
- `due_date` — if a deadline is mentioned (YYYY-MM-DD)
- `priority` — low | medium | high
- `suggested_tags` — tags for Obsidian

**Classification guidance:**
- German and Chinese content is expected — handle both naturally
- When unsure between two intents, prefer the more specific one
- Always extract at minimum: title, summary, keywords
- If the text is ambiguous, use `unknown` rather than guessing wrong

Claude outputs a single JSON object with all metadata.

### Step 3: Execute + Store (Script)

Claude calls the store script with the combined data:

```bash
python3 scripts/obsidian_store.py write \
  --event event.json \
  --transcript transcript.json \
  --intent intent.json
```

This writes to the Obsidian vault:
1. **Inbox** — full record with frontmatter (always)
2. **Daily note** — summary line appended (if intent confidence sufficient)
3. **Project folder** — routed note (if project identified)
4. **Pending** — queued reminder/command (if applicable)

Vault layout:
```
Inbox/Voice/YYYY-MM-DD.md          # Raw inbox entries
Daily/YYYY-MM-DD.md                 # Daily notes (appended)
Projects/<project>/Notes/...        # Project-routed notes
Summaries/Daily/YYYY-MM-DD.md       # Daily digests
Summaries/Weekly/YYYY-Www.md        # Weekly digests
Pending/Reminders.md                # Unconfirmed reminders
Pending/Commands.md                 # Unconfirmed command requests
```

### Step 4: Action Policy

**Safety-first**: only write operations execute automatically.

**Always safe (auto-execute):**
- Write to Obsidian vault (inbox, daily note, project folder)
- Generate structured summaries
- Append to daily note
- Write pending reminders/commands to confirmation queue

**NEVER auto-execute (always queue to Pending/):**
- Sending messages to any platform
- Deleting files
- Executing system commands
- Modifying system settings

For `command_request` and `reminder_request`: always write to Pending/, never execute.

## Error Handling

| Error Type | Behavior |
|---|---|
| Missing required fields in event | Log error, return friendly message, do NOT write to vault |
| Audio file not found | Log error, write raw event to `Pending/` in vault |
| STT transcription failure | Log error, write raw event to `Pending/` with `transcript_status: failed` |
| Obsidian write failure | Log error, retry once, then alert (do not silently drop) |

## Security Boundaries

### Always Safe (auto-execute)
- `obsidian_store.write_note()` — create/update notes
- `obsidian_store.append_daily()` — add to daily note
- `obsidian_store.write_digest()` — generate digest files
- Writing to pending confirmation queues

### Requires Human Confirmation
- Any `command_request` (even if in allowlist)
- Routing to project folders for the first time (unknown project)
- Overwriting an existing digest

### Always Forbidden (unless config explicitly enables)
- Sending messages via Telegram/WhatsApp bridge
- Deleting any files in the vault
- Executing shell commands not in the allowlist
- Modifying the configuration file programmatically

## Configuration

Copy `config/settings.example.yaml` to `config/settings.yaml` and adjust.
All paths, commands, and STT settings are read from config — nothing is hardcoded.

Key config sections:
- `vault.path` — Obsidian vault root directory
- `stt.adapter` — `faster_whisper` | `whisper` | custom module path
- `stt.model` — model name (e.g., `small`, `medium`, `large-v3`)
- `stt.device` — `cuda` | `cpu`
- `obsidian_cli.path` — path to Obsidian CLI if using one
- `actions.allowed_commands` — list of command templates
- `logging.level` — `DEBUG` | `INFO` | `WARNING` | `ERROR`

## Script Reference

| Script | Purpose |
|---|---|
| `scripts/transcribe_audio.py` | STT adapter layer (pluggable backend) |
| `scripts/obsidian_store.py` | All Obsidian vault operations |
| `scripts/ingest_voice.py` | Full pipeline (transcribe only, Claude classifies) |
| `scripts/daily_digest.py` | Generate daily summary |
| `scripts/weekly_digest.py` | Generate weekly summary |
| `scripts/config_loader.py` | Configuration loading + validation |
| `scripts/models.py` | Data models and event schema |
| `scripts/intent_router.py` | Fallback keyword classifier (offline use) |
| `scripts/action_executor.py` | Safe action execution with allowlist |

## Digest Generation

### Daily Digest (run at ~22:00)
```bash
python3 scripts/daily_digest.py --date 2025-01-15
```

### Weekly Digest (run Sunday ~21:30)
```bash
python3 scripts/weekly_digest.py --week 2025-W02
```

Both scripts read from the vault's `Inbox/Voice/` directory, cluster by topic,
and write structured summaries to `Summaries/`.

## When to Only Record (No Execution)

- `command_request` intent → always record, never auto-execute
- `reminder_request` intent → write to pending queue, do not set system reminders
- Unknown intent → record with full metadata for manual triage
- Any action where config `safe_mode` is `true` → record only

## When to Require Human Confirmation

- First encounter of a new project name
- Any `command_request` (even allowlisted)
- Overwriting an existing digest
- STT confidence below configurable threshold (default: 0.5)

## Language Support

- German (`de`) and Chinese (`zh`) content receives priority handling
- `language_hint` from the event is passed to STT
- All multilingual content is stored with `detected_language` in frontmatter
