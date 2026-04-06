"""Intent classification and metadata extraction for voice transcripts.

Uses local keyword matching as the default classifier.
Optionally uses Claude API for enhanced classification when configured.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from models import Intent, IntentResult, Priority, TranscriptResult

logger = logging.getLogger(__name__)

# Priority keywords that map to priority levels
_PRIORITY_KEYWORDS: dict[Priority, list[str]] = {
    Priority.HIGH: ["dringend", "urgent", "紧急", "wichtig", "important", "asap", " sofort"],
    Priority.MEDIUM: ["bald", "soon", "尽快", "demnächst", "近期"],
    Priority.LOW: ["irgendwann", "someday", "以后", "optional", "可选"],
}


def _match_keywords(text: str, patterns: dict[str, list[str]]) -> dict[str, int]:
    """Count keyword matches for each intent category."""
    text_lower = text.lower()
    scores: dict[str, int] = {}
    for intent_name, keywords in patterns.items():
        score = sum(1 for kw in keywords if kw.lower() in text_lower)
        if score > 0:
            scores[intent_name] = score
    return scores


def _extract_priority(text: str) -> Priority | None:
    """Extract priority from text."""
    for priority, keywords in _PRIORITY_KEYWORDS.items():
        if any(kw.lower() in text.lower() for kw in keywords):
            return priority
    return None


def _extract_due_date(text: str) -> str | None:
    """Extract date mentions from text (simple heuristic).

    Looks for patterns like:
    - "morgen" / "明天" (tomorrow)
    - "heute" / "今天" (today)
    - "montag", "dienstag", etc.
    - "下周一" (next Monday)
    - Date patterns like "15.", "am 15."
    """
    from datetime import date, timedelta

    text_lower = text.lower()
    today = date.today()

    # German relative dates
    if "heute" in text_lower or "今天" in text:
        return today.isoformat()
    if "morgen" in text_lower and "morgend" not in text_lower or "明天" in text:
        return (today + timedelta(days=1)).isoformat()
    if "übermorgen" in text_lower or "后天" in text:
        return (today + timedelta(days=2)).isoformat()

    # German weekdays
    weekday_map = {
        "montag": 0, "dienstag": 1, "mittwoch": 2,
        "donnerstag": 3, "freitag": 4, "samstag": 5, "sonntag": 6,
        "周一": 0, "周二": 1, "周三": 2, "周四": 3, "周五": 4, "周六": 5, "周日": 6,
    }
    for name, wd in weekday_map.items():
        if name in text_lower:
            days_ahead = (wd - today.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7  # Next week if today
            if "nächste" in text_lower or "下" in text:
                days_ahead = (wd - today.weekday()) % 7 or 7
            return (today + timedelta(days=days_ahead)).isoformat()

    # "am DD." pattern (German date)
    m = re.search(r"\bam (\d{1,2})\.", text_lower)
    if m:
        day = int(m.group(1))
        try:
            target = today.replace(day=day)
            if target < today:
                target = target.replace(month=today.month + 1) if today.month < 12 else target.replace(year=today.year + 1, month=1)
            return target.isoformat()
        except ValueError:
            pass

    return None


def _extract_keywords(text: str) -> list[str]:
    """Extract meaningful keywords from text (simple heuristic).

    Removes common stop words and returns unique meaningful terms.
    """
    stop_words = {
        # German
        "der", "die", "das", "ein", "eine", "und", "oder", "ist", "sind",
        "ich", "du", "er", "sie", "es", "wir", "ihr", "mein", "dein",
        "haben", "sein", "werden", "können", "müssen", "sollen", "wollen",
        "mit", "auf", "in", "an", "von", "zu", "für", "bei", "nach", "aus",
        # Chinese
        "的", "了", "在", "是", "我", "你", "他", "她", "它", "们",
        "和", "或", "但", "这个", "那个", "有", "没", "不", "也",
        # English
        "the", "a", "an", "and", "or", "but", "is", "are", "was", "were",
        "i", "you", "he", "she", "it", "we", "they", "my", "your",
        "have", "has", "been", "will", "would", "could", "should",
    }

    # Split by whitespace and Chinese character boundaries
    tokens = re.findall(r"[\u4e00-\u9fff]|[a-zA-ZäöüßÄÖÜ]+", text.lower())
    keywords = [t for t in tokens if t not in stop_words and len(t) > 1]

    # Deduplicate while preserving order
    seen: set[str] = set()
    result: list[str] = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            result.append(kw)
    return result[:15]


def classify_local(
    text: str,
    keyword_patterns: dict[str, list[str]],
) -> IntentResult:
    """Classify intent using local keyword matching.

    Falls back to Intent.UNKNOWN if no keywords match.
    """
    scores = _match_keywords(text, keyword_patterns)

    if scores:
        best_intent = max(scores, key=scores.get)  # type: ignore
        confidence = min(scores[best_intent] / 3.0, 1.0)
    else:
        best_intent = Intent.UNKNOWN.value
        confidence = 0.0

    keywords = _extract_keywords(text)
    priority = _extract_priority(text)
    due_date = _extract_due_date(text)

    return IntentResult(
        intent=Intent(best_intent),
        confidence=confidence,
        keywords=keywords,
        priority=priority,
        due_date=due_date,
        suggested_tags=[keywords[0]] if keywords else [],
    )


def classify_with_claude(
    text: str,
    detected_language: str,
    claude_model: str,
) -> IntentResult | None:
    """Classify intent using Claude API for better accuracy.

    Requires ANTHROPIC_API_KEY environment variable.
    Returns None if Claude API is not available.
    """
    try:
        import anthropic  # type: ignore
        import os

        api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
        if not api_key:
            return None

        client = anthropic.Anthropic(api_key=api_key)

        prompt = f"""Analyze this voice transcript and classify the user's intent.
Return ONLY valid JSON (no markdown) with this exact structure:
{{
  "intent": "one of: capture_idea, task, journal, project_update, meeting_note, knowledge, reminder_request, command_request, unknown",
  "confidence": 0.0-1.0,
  "title": "brief title",
  "summary": "1-2 sentence summary",
  "keywords": ["keyword1", "keyword2"],
  "entities": {{"person": ["name"], "project": ["name"], "date": ["date"]}},
  "project": "project name or null",
  "action_items": ["action 1"],
  "due_date": "YYYY-MM-DD or null",
  "priority": "low/medium/high or null",
  "suggested_tags": ["tag1"]
}}

Detected language: {detected_language}

Transcript:
{text}"""

        response = client.messages.create(
            model=claude_model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        content = response.content[0].text.strip()
        # Strip markdown code block if present
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0]

        data = json.loads(content)
        return IntentResult(
            intent=Intent(data.get("intent", "unknown")),
            confidence=data.get("confidence", 0.5),
            title=data.get("title"),
            summary=data.get("summary"),
            keywords=data.get("keywords", []),
            entities=data.get("entities", {}),
            project=data.get("project"),
            action_items=data.get("action_items", []),
            due_date=data.get("due_date"),
            priority=Priority(data["priority"]) if data.get("priority") else None,
            suggested_tags=data.get("suggested_tags", []),
        )
    except Exception as e:
        logger.warning(f"Claude classification failed, falling back to local: {e}")
        return None


def classify(
    transcript: TranscriptResult,
    config: Any,
) -> IntentResult:
    """Classify intent from transcript text.

    Uses Claude API if configured and available, otherwise falls back
    to local keyword matching.
    """
    text = transcript.transcript
    if not text:
        return IntentResult(intent=Intent.UNKNOWN, confidence=0.0)

    # Try Claude API first if configured
    if config.get("intent.use_claude", False):
        claude_result = classify_with_claude(
            text=text,
            detected_language=transcript.detected_language,
            claude_model=config.get("intent.claude_model", "claude-sonnet-4-20250514"),
        )
        if claude_result is not None:
            return claude_result

    # Fallback to local keyword matching
    patterns = config.get("intent.keyword_patterns", {})
    result = classify_local(text, patterns)

    # Generate a simple title from first few words
    if not result.title:
        words = text.split()[:6]
        result.title = " ".join(words) + ("..." if len(words) >= 6 else "")

    # Generate summary from first sentence
    if not result.summary:
        sentences = re.split(r"[.!?。！？]", text, maxsplit=1)
        result.summary = sentences[0].strip() if sentences else text[:100]

    return result
