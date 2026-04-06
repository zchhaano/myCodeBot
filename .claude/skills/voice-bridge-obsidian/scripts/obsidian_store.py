"""Obsidian vault storage operations.

Supports three backends:
- file: Direct filesystem writes (default, recommended)
- cli: Use obsidian-cli if installed
- api: Use Obsidian Local REST API plugin

All methods ensure directories exist before writing.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from models import Intent, IntentResult, Priority, ProcessedRecord, TranscriptResult

logger = logging.getLogger(__name__)


def _yaml_sanitize(value: Any) -> Any:
    """Ensure YAML-safe values for frontmatter."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, list):
        return [_yaml_sanitize(v) for v in value]
    return str(value)


def _build_frontmatter(data: dict[str, Any]) -> str:
    """Build YAML frontmatter block."""
    sanitized = {k: _yaml_sanitize(v) for k, v in data.items() if v is not None}
    return "---\n" + yaml.dump(sanitized, allow_unicode=True, default_flow_style=False).strip() + "\n---"


def _build_note_body(record: ProcessedRecord) -> str:
    """Build the markdown body for a voice note entry."""
    lines: list[str] = []

    # Header
    timestamp_dt = datetime.fromisoformat(record.event.timestamp.replace("Z", "+00:00"))
    time_str = timestamp_dt.strftime("%H:%M")
    lines.append(f"### Voice Note — {time_str}")
    lines.append("")

    # Metadata callout
    user_name = record.event.contact_name or record.event.user_id
    lines.append(f"> [!info] Metadata")
    lines.append(f"> **Platform**: {record.event.platform.value} | **User**: {user_name} | **Intent**: {record.intent.intent.value}")
    lang = record.transcript.detected_language
    conf = record.transcript.confidence
    if conf is not None:
        lines.append(f"> **Language**: {lang} | **Confidence**: {conf:.2f}")
    else:
        lines.append(f"> **Language**: {lang}")
    lines.append("")

    # Transcript
    if record.transcript.transcript:
        lines.append("## Transcript")
        lines.append("")
        lines.append(record.transcript.transcript)
        lines.append("")

    # Summary
    if record.intent.summary:
        lines.append("## Summary")
        lines.append("")
        lines.append(record.intent.summary)
        lines.append("")

    # Title
    if record.intent.title:
        lines.append(f"**Title**: {record.intent.title}")
        lines.append("")

    # Action items
    if record.intent.action_items:
        lines.append("## Action Items")
        lines.append("")
        for item in record.intent.action_items:
            lines.append(f"- [ ] {item}")
        lines.append("")

    # Keywords
    if record.intent.keywords:
        lines.append("## Keywords")
        lines.append("")
        lines.append(", ".join(record.intent.keywords))
        lines.append("")

    # Entities
    if record.intent.entities:
        lines.append("## Entities")
        lines.append("")
        for entity_type, names in record.intent.entities.items():
            lines.append(f"- **{entity_type.title()}**: {', '.join(names)}")
        lines.append("")

    # Tags
    tags = record.intent.suggested_tags + [record.intent.intent.value, lang]
    if record.intent.project:
        tags.append(record.intent.project)
    tag_str = " ".join(f"#{t}" for t in set(tags) if t)
    if tag_str:
        lines.append(f"**Tags**: {tag_str}")
        lines.append("")

    # System notes
    lines.append("## System Notes")
    lines.append("")
    if conf is not None:
        lines.append(f"- STT Confidence: {conf:.2f}")
    lines.append(f"- Detected Language: {lang}")
    lines.append(f"- Transcript Status: {record.transcript.status.value}")
    if record.event.text_caption:
        lines.append(f"- Original Caption: {record.event.text_caption}")
    lines.append("")

    return "\n".join(lines)


class ObsidianStore:
    """Handles all Obsidian vault read/write operations."""

    def __init__(self, config: Any) -> None:
        self.config = config
        self.vault_path: Path = config.vault_path
        self.method: str = config.obsidian_method

    def _ensure_dir(self, path: Path) -> None:
        """Create directory if it doesn't exist."""
        path.mkdir(parents=True, exist_ok=True)

    def _folder(self, key: str) -> Path:
        """Get absolute path for a vault folder key."""
        return self.config.folder_path(key)

    def write_note(
        self,
        record: ProcessedRecord,
        content: str | None = None,
    ) -> Path:
        """Write a voice note to the inbox.

        Appends to the daily inbox file (Inbox/Voice/YYYY-MM-DD.md).
        """
        inbox_dir = self._folder("inbox")
        self._ensure_dir(inbox_dir)

        today = date.today().isoformat()
        inbox_file = inbox_dir / f"{today}.md"

        body = content or _build_note_body(record)
        frontmatter = _build_frontmatter(record.to_frontmatter())

        # If file exists, append; otherwise create with frontmatter
        if inbox_file.exists():
            with open(inbox_file, "a", encoding="utf-8") as f:
                f.write("\n---\n\n")
                f.write(body)
                f.write("\n")
        else:
            with open(inbox_file, "w", encoding="utf-8") as f:
                f.write(frontmatter)
                f.write("\n\n")
                f.write(body)
                f.write("\n")

        logger.info(f"Written to inbox: {inbox_file}")
        return inbox_file

    def append_daily(self, record: ProcessedRecord) -> Path | None:
        """Append a summary line to the daily note.

        Only appends for non-unknown intents with reasonable confidence.
        """
        if record.intent.intent == Intent.UNKNOWN:
            return None
        if record.intent.confidence < self.config.get("intent.confidence_threshold", 0.5):
            return None

        daily_dir = self._folder("daily")
        self._ensure_dir(daily_dir)

        today = date.today().isoformat()
        daily_file = daily_dir / f"{today}.md"

        time_str = datetime.now().strftime("%H:%M")
        user_name = record.event.contact_name or record.event.user_id
        summary = record.intent.summary or record.transcript.transcript[:100]
        intent = record.intent.intent.value

        entry = (
            f"- **{time_str}** [{user_name}] ({intent}): {summary}"
        )

        if daily_file.exists():
            with open(daily_file, "a", encoding="utf-8") as f:
                f.write(f"\n{entry}")
        else:
            with open(daily_file, "w", encoding="utf-8") as f:
                f.write(f"---\ndate: {today}\ntype: daily_note\n---\n\n")
                f.write(f"# Daily Note — {today}\n\n")
                f.write("## Voice Notes\n\n")
                f.write(entry)

        logger.info(f"Appended to daily note: {daily_file}")
        return daily_file

    def write_to_project(self, record: ProcessedRecord) -> Path | None:
        """Route note to a project directory if a project is identified."""
        project = record.intent.project
        if not project:
            return None

        # Sanitize project name for filesystem
        safe_name = re.sub(r'[^\w\s-]', '', project).strip().replace(' ', '-')
        project_dir = self._folder("projects") / safe_name / "Notes"
        self._ensure_dir(project_dir)

        timestamp_dt = datetime.now()
        filename = f"voice-{timestamp_dt.strftime('%Y-%m-%d-%H%M%S')}.md"
        project_file = project_dir / filename

        body = _build_note_body(record)
        frontmatter = _build_frontmatter(record.to_frontmatter())

        with open(project_file, "w", encoding="utf-8") as f:
            f.write(frontmatter)
            f.write("\n\n")
            f.write(body)
            f.write("\n")

        logger.info(f"Written to project: {project_file}")
        return project_file

    def write_pending(
        self,
        record: ProcessedRecord,
        category: str,
        note: str = "",
    ) -> Path:
        """Write to pending confirmation queue.

        category: "reminders" or "commands"
        """
        pending_dir = self._folder("pending")
        self._ensure_dir(pending_dir)

        pending_file = pending_dir / f"{category.title()}.md"
        timestamp = datetime.now().isoformat()
        user_name = record.event.contact_name or record.event.user_id

        entry = (
            f"\n## {timestamp}\n"
            f"- **User**: {user_name}\n"
            f"- **Platform**: {record.event.platform.value}\n"
            f"- **Transcript**: {record.transcript.transcript[:200]}\n"
            f"- **Intent**: {record.intent.intent.value}\n"
        )
        if note:
            entry += f"- **Note**: {note}\n"
        if record.intent.action_items:
            entry += f"- **Actions**: {', '.join(record.intent.action_items)}\n"

        if pending_file.exists():
            with open(pending_file, "a", encoding="utf-8") as f:
                f.write(entry)
        else:
            with open(pending_file, "w", encoding="utf-8") as f:
                f.write(f"---\ntype: pending_{category}\ncreated: {date.today().isoformat()}\n---\n\n")
                f.write(f"# Pending {category.title()}\n\n")
                f.write("> [!warning] These items require human confirmation before execution.\n")
                f.write(entry)

        logger.info(f"Written to pending {category}: {pending_file}")
        return pending_file

    def write_digest(
        self,
        content: str,
        frontmatter_data: dict[str, Any],
        digest_type: str,
        filename: str,
    ) -> Path:
        """Write a digest file (daily or weekly).

        digest_type: "daily" or "weekly"
        filename: e.g., "2025-01-15.md" or "2025-W02.md"
        """
        key = f"summaries_{digest_type}"
        digest_dir = self._folder(key)
        self._ensure_dir(digest_dir)

        digest_file = digest_dir / filename

        fm = _build_frontmatter(frontmatter_data)
        with open(digest_file, "w", encoding="utf-8") as f:
            f.write(fm)
            f.write("\n\n")
            f.write(content)
            f.write("\n")

        logger.info(f"Written {digest_type} digest: {digest_file}")
        return digest_file

    def read_inbox_day(self, target_date: date) -> list[dict[str, Any]]:
        """Read all voice entries from inbox for a given date.

        Returns list of parsed entries with frontmatter and body.
        """
        inbox_dir = self._folder("inbox")
        inbox_file = inbox_dir / f"{target_date.isoformat()}.md"

        if not inbox_file.exists():
            return []

        content = inbox_file.read_text(encoding="utf-8")

        # Parse frontmatter
        entries: list[dict[str, Any]] = []
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    fm = yaml.safe_load(parts[1])
                except yaml.YAMLError:
                    fm = {}
                body = parts[2]
                entries.append({"frontmatter": fm or {}, "body": body})

        return entries

    def read_daily_notes(self, start: date, end: date) -> list[dict[str, Any]]:
        """Read all daily notes in a date range."""
        daily_dir = self._folder("daily")
        entries: list[dict[str, Any]] = []

        current = start
        while current <= end:
            note_file = daily_dir / f"{current.isoformat()}.md"
            if note_file.exists():
                content = note_file.read_text(encoding="utf-8")
                entries.append({"date": current.isoformat(), "content": content})
            current = date.fromordinal(current.toordinal() + 1)

        return entries
