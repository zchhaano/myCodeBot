# Obsidian Vault Schema Reference

## Frontmatter Fields (YAML)

Every voice record includes these frontmatter fields:

```yaml
---
source_platform: telegram | whatsapp
source_user: "user_id or contact_name"
timestamp: "2025-01-15T14:30:00Z"
intent: capture_idea | task | journal | project_update | meeting_note | knowledge | reminder_request | command_request | unknown
tags:
  - voice
  - <intent>
  - <detected_language>
project: "project name or null"
audio_file: "/path/to/original/audio.ogg"
transcript_status: success | failed | partial
processed_at: "2025-01-15T14:30:15Z"
keywords:
  - keyword1
  - keyword2
priority: low | medium | high | null
due_date: "2025-01-20" | null
---
```

## Note Body Template

```markdown
## Transcript

<Raw transcript text>

## Summary

<Cleaned-up summary>

## Action Items

- [ ] <action item 1>
- [ ] <action item 2>

## Keywords

<comma-separated keywords>

## Entities

- **Person**: <names>
- **Project**: <project name>
- **Date**: <mentioned dates>

## System Notes

- STT Confidence: 0.92
- Detected Language: de
- Processing time: 1.2s
```

## Vault Folder Structure

```
vault/
├── Inbox/
│   └── Voice/
│       └── 2025-01-15.md        # Append-mode: all voice records for the day
├── Daily/
│   └── 2025-01-15.md            # Daily note (voice entries appended here)
├── Projects/
│   ├── my-project/
│   │   └── Notes/
│   │       └── voice-2025-01-15-143000.md
│   └── another-project/
│       └── Notes/
├── Summaries/
│   ├── Daily/
│   │   └── 2025-01-15.md
│   └── Weekly/
│       └── 2025-W02.md
└── Pending/
    ├── Reminders.md             # Pending reminder requests
    └── Commands.md              # Pending command requests
```

## Inbox Entry Format

The `Inbox/Voice/YYYY-MM-DD.md` file is append-only. Each entry is separated by `---`:

```markdown
---
### 🎙️ Voice Note — 14:30

> [!info] Metadata
> **Platform**: Telegram | **User**: John | **Intent**: capture_idea
> **Language**: de | **Confidence**: 0.92

**Transcript**: Ich hatte eine Idee für das neue Projekt...

**Summary**: Idea for the new project regarding...

**Tags**: #voice #capture_idea #de

---
```

## Digest Frontmatter

### Daily Digest

```yaml
---
type: daily_digest
date: "2025-01-15"
total_voice_notes: 12
intents:
  capture_idea: 5
  task: 3
  journal: 2
  knowledge: 1
  unknown: 1
languages:
  de: 8
  zh: 3
  en: 1
generated_at: "2025-01-15T22:00:05Z"
---
```

### Weekly Digest

```yaml
---
type: weekly_digest
week: "2025-W02"
date_range: "2025-01-06 — 2025-01-12"
total_voice_notes: 67
top_intents:
  - capture_idea: 25
  - task: 18
  - journal: 10
generated_at: "2025-01-12T21:30:05Z"
---
```
