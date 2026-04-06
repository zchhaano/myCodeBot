#!/usr/bin/env python3
"""Weekly digest generator — summarizes all voice notes for a given week.

Reads daily digests (or raw inbox entries) for the week and produces
a structured summary in Summaries/Weekly/YYYY-Www.md.

Usage:
    python scripts/weekly_digest.py                      # This week
    python scripts/weekly_digest.py --week 2025-W02      # Specific week
    python scripts/weekly_digest.py --start 2025-01-06   # Start date
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

from config_loader import Config
from obsidian_store import ObsidianStore

logger = logging.getLogger(__name__)


def _iso_week_start(year: int, week: int) -> date:
    """Get the Monday of a given ISO week."""
    jan4 = date(year, 1, 4)
    start_of_week1 = jan4 - timedelta(days=jan4.weekday())
    return start_of_week1 + timedelta(weeks=week - 1)


def _parse_week_string(week_str: str) -> tuple[int, int]:
    """Parse a week string like '2025-W02' into (year, week_number)."""
    parts = week_str.upper().split("-W")
    if len(parts) != 2:
        raise ValueError(f"Invalid week format: {week_str}. Use YYYY-Www (e.g., 2025-W02)")
    return int(parts[0]), int(parts[1])


def generate_weekly_digest(
    start_date: date,
    config: Config,
) -> dict[str, Any]:
    """Generate a weekly digest for the week starting on start_date (Monday).

    Reads daily summaries or inbox entries for Mon-Sun and produces
    a structured weekly summary.
    """
    store = ObsidianStore(config)
    end_date = start_date + timedelta(days=6)

    # Collect all entries for the week
    all_content: list[str] = []
    intent_counts: Counter = Counter()
    language_counts: Counter = Counter()
    all_keywords: list[str] = []
    all_action_items: list[str] = []
    projects_mentioned: list[str] = []
    daily_summaries: list[str] = []
    total_notes = 0

    current = start_date
    while current <= end_date:
        entries = store.read_inbox_day(current)
        if entries:
            total_notes += len(entries)
            for entry in entries:
                fm = entry.get("frontmatter", {})
                body = entry.get("body", "")

                # Extract intent
                intent = fm.get("intent", "unknown")
                intent_counts[intent] += 1

                # Extract language
                tags = fm.get("tags", [])
                for tag in tags:
                    if len(tag) == 2:  # Language codes are 2 chars
                        language_counts[tag] += 1

                # Extract keywords
                keywords = fm.get("keywords", [])
                all_keywords.extend(keywords)

                # Extract project
                project = fm.get("project")
                if project:
                    projects_mentioned.append(project)

                # Collect action items from body
                for line in body.split("\n"):
                    if line.strip().startswith("- [ ]"):
                        all_action_items.append(line.strip().replace("- [ ] ", ""))

                all_content.append(body)
                daily_summaries.append(f"### {current.isoformat()}\n{body[:200]}...")

        current = date.fromordinal(current.toordinal() + 1)

    if total_notes == 0:
        return {
            "status": "no_data",
            "week": f"{start_date.isoformat()} — {end_date.isoformat()}",
            "message": "No voice notes found for this week",
        }

    # Compute keyword frequency
    keyword_freq = Counter(all_keywords).most_common(15)

    # Compute project frequency
    project_freq = Counter(projects_mentioned).most_common(10)

    # Build digest content
    iso_cal = start_date.isocalendar()
    week_label = f"{iso_cal[0]}-W{iso_cal[1]:02d}"

    lines: list[str] = []
    lines.append(f"# Weekly Digest — {week_label}")
    lines.append(f"> {start_date.isoformat()} — {end_date.isoformat()}")
    lines.append("")

    # Overview
    lines.append("## Overview")
    lines.append("")
    lines.append(f"- **Total voice notes**: {total_notes}")
    lines.append(f"- **Days with activity**: {len([s for s in daily_summaries if s])}/{7}")
    lines.append(f"- **Action items**: {len(all_action_items)}")
    lines.append(f"- **Projects mentioned**: {len(set(projects_mentioned))}")
    lines.append("")

    # Key themes (top keywords)
    lines.append("## Key Themes")
    lines.append("")
    for kw, count in keyword_freq[:10]:
        lines.append(f"- **{kw}** (mentioned {count}x)")
    lines.append("")

    # Intent distribution
    lines.append("## Intent Distribution")
    lines.append("")
    for intent, count in intent_counts.most_common():
        lines.append(f"- {intent}: {count}")
    lines.append("")

    # Language distribution
    if language_counts:
        lines.append("## Languages")
        lines.append("")
        for lang, count in language_counts.most_common():
            lines.append(f"- {lang}: {count}")
        lines.append("")

    # Key progress
    if project_freq:
        lines.append("## Project Activity")
        lines.append("")
        for project, count in project_freq:
            lines.append(f"- **{project}**: {count} mentions")
        lines.append("")

    # Outstanding action items
    if all_action_items:
        lines.append("## Outstanding Action Items")
        lines.append("")
        seen = set()
        for item in all_action_items:
            if item not in seen:
                seen.add(item)
                lines.append(f"- [ ] {item}")
        lines.append("")

    # Ideas worth deepening (capture_idea entries)
    lines.append("## Ideas Worth Deepening")
    lines.append("")
    lines.append("> Review these ideas from the week and decide which to pursue.")
    lines.append("")
    # Simple heuristic: first 5 capture_idea entries
    idea_count = 0
    for content in all_content:
        if idea_count >= 5:
            break
        # Look for capture_idea content
        if any(kw in content.lower() for kw in ["idee", "想法", "灵感", "gedanke"]):
            first_line = content.strip().split("\n")[0][:100]
            lines.append(f"- {first_line}")
            idea_count += 1
    if idea_count == 0:
        lines.append("- *(No explicit ideas captured this week)*")
    lines.append("")

    # Suggestions for next week
    lines.append("## Suggestions for Next Week")
    lines.append("")
    if all_action_items:
        lines.append(f"- Review and resolve {len(all_action_items)} open action items")
    if project_freq:
        lines.append(f"- Continue progress on: {', '.join(p for p, _ in project_freq[:3])}")
    lines.append("- Set up recurring voice capture for daily reflections")
    lines.append("")

    # Daily breakdown
    lines.append("## Daily Breakdown")
    lines.append("")
    for summary in daily_summaries:
        lines.append(summary)
        lines.append("")

    # Build frontmatter
    frontmatter = {
        "type": "weekly_digest",
        "week": week_label,
        "date_range": f"{start_date.isoformat()} — {end_date.isoformat()}",
        "total_voice_notes": total_notes,
        "top_intents": [{"intent": k, "count": v} for k, v in intent_counts.most_common(5)],
        "generated_at": datetime.now().isoformat(),
    }

    content = "\n".join(lines)
    filename = f"{week_label}.md"

    store.write_digest(content, frontmatter, "weekly", filename)

    logger.info(f"Weekly digest generated for {week_label}")
    return {
        "status": "success",
        "week": week_label,
        "file": filename,
        "stats": {
            "total_notes": total_notes,
            "intents": dict(intent_counts),
            "languages": dict(language_counts),
            "action_items": len(all_action_items),
            "projects": list(set(projects_mentioned)),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate weekly voice digest")
    parser.add_argument("--week", type=str, help="Week in YYYY-Www format (e.g., 2025-W02)")
    parser.add_argument("--start", type=str, help="Start date (Monday) in YYYY-MM-DD format")
    parser.add_argument("--config", type=str, default=None, help="Path to settings.yaml")
    args = parser.parse_args()

    # Determine start date (Monday of the week)
    if args.week:
        year, week = _parse_week_string(args.week)
        start_date = _iso_week_start(year, week)
    elif args.start:
        start_date = date.fromisoformat(args.start)
    else:
        today = date.today()
        # Go back to Monday of current week
        start_date = today - timedelta(days=today.weekday())

    config = Config.load_or_bootstrap(args.config)

    # Setup logging
    log_dir = Path(config.get("logging.dir", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO)

    result = generate_weekly_digest(start_date, config)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
