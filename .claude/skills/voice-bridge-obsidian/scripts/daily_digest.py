#!/usr/bin/env python3
"""Daily digest generator — summarizes all voice notes for a given day.

Reads from Inbox/Voice/YYYY-MM-DD.md and produces a structured summary
in Summaries/Daily/YYYY-MM-DD.md.

Usage:
    python scripts/daily_digest.py                       # Today
    python scripts/daily_digest.py --date 2025-01-15     # Specific date
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

from config_loader import Config
from obsidian_store import ObsidianStore

logger = logging.getLogger(__name__)


def _extract_entries_from_inbox(content: str) -> list[dict[str, str]]:
    """Extract individual voice entries from inbox file content."""
    entries = []
    # Split by horizontal rules that separate entries
    parts = content.split("---\n\n")
    for part in parts:
        part = part.strip()
        if not part or part.startswith("---"):  # Skip frontmatter
            continue
        entries.append({"raw": part})
    return entries


def _build_digest_content(
    target_date: date,
    entries: list[dict[str, Any]],
    intent_counts: Counter,
    language_counts: Counter,
    all_keywords: list[str],
    all_action_items: list[str],
    store: ObsidianStore,
) -> str:
    """Build the daily digest markdown content."""
    lines: list[str] = []

    lines.append(f"# Daily Voice Digest — {target_date.isoformat()}")
    lines.append("")

    # Overview
    lines.append("## Overview")
    lines.append("")
    lines.append(f"- **Total voice notes**: {len(entries)}")
    lines.append(f"- **Languages**: {', '.join(f'{k} ({v})' for k, v in language_counts.most_common())}")
    lines.append("")

    # Intent breakdown
    lines.append("## Intent Breakdown")
    lines.append("")
    for intent_name, count in intent_counts.most_common():
        lines.append(f"- **{intent_name}**: {count}")
    lines.append("")

    # Top keywords / themes
    keyword_counts = Counter(all_keywords)
    if keyword_counts:
        lines.append("## Key Themes")
        lines.append("")
        for kw, count in keyword_counts.most_common(10):
            lines.append(f"- {kw} ({count}x)")
        lines.append("")

    # Action items
    if all_action_items:
        lines.append("## Action Items")
        lines.append("")
        for item in all_action_items:
            lines.append(f"- [ ] {item}")
        lines.append("")

    # Open questions and follow-ups
    lines.append("## Open Items")
    lines.append("")
    lines.append("> [!note] Review these items from today's voice notes.")
    lines.append("")

    # Footer
    lines.append("---")
    lines.append(f"*Generated at {datetime.now().isoformat()}*")

    return "\n".join(lines)


def generate_daily_digest(
    target_date: date,
    config: Config,
) -> dict[str, Any]:
    """Generate a daily digest for the given date.

    Returns a result dict with the digest file path and statistics.
    """
    store = ObsidianStore(config)
    entries = store.read_inbox_day(target_date)

    if not entries:
        logger.info(f"No voice entries found for {target_date}")
        return {"status": "no_data", "date": target_date.isoformat()}

    # Aggregate statistics
    intent_counts: Counter = Counter()
    language_counts: Counter = Counter()
    all_keywords: list[str] = []
    all_action_items: list[str] = []

    for entry in entries:
        fm = entry.get("frontmatter", {})

        # Count intents
        if intent := fm.get("intent"):
            intent_counts[intent] += 1

        # Count languages
        for tag in fm.get("tags", []):
            if len(tag) == 2 and tag.isalpha():  # Likely a language code
                language_counts[tag] += 1

        # Collect keywords
        all_keywords.extend(fm.get("keywords", []))

        # Extract action items from body
        body = entry.get("body", "")
        for line in body.split("\n"):
            if line.strip().startswith("- [ ]"):
                item = line.strip().replace("- [ ] ", "")
                all_action_items.append(item)

    # Build and write digest
    content = _build_digest_content(
        target_date=target_date,
        entries=entries,
        intent_counts=intent_counts,
        language_counts=language_counts,
        all_keywords=all_keywords,
        all_action_items=all_action_items,
        store=store,
    )

    frontmatter = {
        "type": "daily_digest",
        "date": target_date.isoformat(),
        "total_voice_notes": len(entries),
        "intents": dict(intent_counts),
        "languages": dict(language_counts),
        "generated_at": datetime.now().isoformat(),
    }

    filename = f"{target_date.isoformat()}.md"
    digest_path = store.write_digest(
        content=content,
        frontmatter_data=frontmatter,
        digest_type="daily",
        filename=filename,
    )

    logger.info(f"Daily digest generated: {digest_path}")
    return {
        "status": "success",
        "date": target_date.isoformat(),
        "file": str(digest_path),
        "stats": {
            "total_notes": len(entries),
            "intents": dict(intent_counts),
            "languages": dict(language_counts),
            "action_items": len(all_action_items),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate daily voice digest")
    parser.add_argument("--date", type=str, help="Date in YYYY-MM-DD format (default: today)")
    parser.add_argument("--config", type=str, default=None, help="Path to settings.yaml")
    args = parser.parse_args()

    # Parse date
    if args.date:
        target_date = date.fromisoformat(args.date)
    else:
        target_date = date.today()

    config = Config.load_or_bootstrap(args.config)

    # Setup logging
    log_dir = Path(config.get("logging.dir", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO)

    result = generate_daily_digest(target_date, config)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
