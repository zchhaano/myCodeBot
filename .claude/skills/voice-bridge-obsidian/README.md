# Voice Bridge Obsidian

A Claude Code skill that processes voice messages from Telegram or WhatsApp via a local bridge service, transcribes them, classifies intent, and archives everything into an Obsidian vault.

## Architecture

```
Bridge Service (Telegram/WhatsApp)
       │
       ▼
  Event JSON + Audio File
       │
       ▼
  ingest_voice.py  ─── Validate → Transcribe → Classify → Execute → Store
       │                │             │              │           │        │
       │          models.py   transcribe_audio.py  intent_router.py  action_executor.py  obsidian_store.py
       │
       ▼
  Obsidian Vault
  ├── Inbox/Voice/YYYY-MM-DD.md
  ├── Daily/YYYY-MM-DD.md
  ├── Projects/<name>/Notes/
  ├── Summaries/Daily/YYYY-MM-DD.md
  ├── Summaries/Weekly/YYYY-Www.md
  └── Pending/
      ├── Reminders.md
      └── Commands.md
```

## Quick Start

### 1. Install Dependencies

```bash
pip install faster-whisper pyyaml
```

### 2. Configure

```bash
cp config/settings.example.yaml config/settings.yaml
# Edit settings.yaml — set your vault path and STT preferences
```

### 3. Test with Sample Event

```bash
python scripts/ingest_voice.py --event examples/sample_event.json --dry-run
```

### 4. Process a Real Voice Message

```bash
python scripts/ingest_voice.py --event /path/to/event.json
```

### 5. Generate Digests

```bash
# Today's digest
python scripts/daily_digest.py

# This week's digest
python scripts/weekly_digest.py
```

## Directory Structure

```
voice-bridge-obsidian/
├── SKILL.md                          # Skill definition (trigger + instructions)
├── README.md                         # This file
├── .env.example                      # Environment variable template
├── config/
│   └── settings.example.yaml         # Configuration template
├── scripts/
│   ├── models.py                     # Event schema and data models
│   ├── config_loader.py              # Configuration loading + validation
│   ├── ingest_voice.py               # Main pipeline entry point
│   ├── transcribe_audio.py           # STT adapter (faster-whisper/whisper)
│   ├── intent_router.py              # Intent classification + extraction
│   ├── obsidian_store.py             # Obsidian vault operations
│   ├── action_executor.py            # Safe action execution
│   ├── daily_digest.py               # Daily summary generator
│   └── weekly_digest.py              # Weekly summary generator
├── examples/
│   └── sample_event.json             # Example bridge event
├── tests/
│   ├── test_fixtures.py              # Test fixtures and factory functions
│   └── test_ingest.py                # Unit tests for ingest pipeline
├── references/
│   └── obsidian_schema.md            # Obsidian vault schema reference
├── logs/                             # Runtime logs (gitignored)
└── evals/
    └── evals.json                    # Skill evaluation prompts
```

## Configuration

All settings are in `config/settings.yaml`. Key sections:

- **vault**: Obsidian vault path and folder structure
- **stt**: Speech-to-text backend, model, device
- **intent**: Intent classification settings
- **actions**: Allowed commands and safe mode
- **logging**: Log level and output paths

See `config/settings.example.yaml` for full options.

## Scheduling

### Cron (Linux/macOS)

```cron
# Daily digest at 22:00
0 22 * * * cd /path/to/voice-bridge-obsidian && python scripts/daily_digest.py >> logs/digest.log 2>&1

# Weekly digest Sunday at 21:30
30 21 * * 0 cd /path/to/voice-bridge-obsidian && python scripts/weekly_digest.py >> logs/digest.log 2>&1
```

### Claude Code Scheduled Tasks

```
/loop 22h "Run the daily voice digest: python scripts/daily_digest.py and report any errors"
```

## Language Support

- German (`de`) and Chinese (`zh`) content is prioritized
- Multilingual intent classification keywords
- Language detection via STT output

## Safety Model

| Action | Auto-execute | Requires Confirmation |
|--------|:---:|:---:|
| Write to Obsidian | ✅ | |
| Append to daily note | ✅ | |
| Generate digests | ✅ | |
| Queue pending reminders | ✅ | |
| Execute allowlisted commands | | ✅ |
| Send messages externally | | ❌ (disabled by default) |
| Delete files | | ❌ (disabled by default) |

## Extensibility

- **STT Backend**: Implement the `STTAdapter` protocol in `transcribe_audio.py`
- **Intent Classifier**: Add patterns to `intent_router.py` or integrate an LLM API
- **Obsidian Backend**: Swap file-based storage for Obsidian REST API
- **Bridge Integration**: Add new platform adapters without touching core logic
