"""Test fixtures and factory functions for voice-bridge-obsidian tests."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sys
from pathlib import Path

# Add scripts dir for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from models import (
    Intent,
    IntentResult,
    Priority,
    ProcessedRecord,
    TranscriptResult,
    TranscriptSegment,
    VoiceEvent,
    Platform,
    TranscriptStatus,
)


def make_event(**overrides: Any) -> VoiceEvent:
    """Create a sample VoiceEvent with optional field overrides."""
    defaults = {
        "platform": Platform.TELEGRAM,
        "user_id": "12345678",
        "chat_id": "-1001234567890",
        "message_id": "42",
        "timestamp": "2025-01-15T14:30:00Z",
        "audio_path": "/tmp/test_audio.ogg",
        "mime_type": "audio/ogg",
        "language_hint": "de",
        "text_caption": None,
        "contact_name": "Test User",
    }
    defaults.update(overrides)
    return VoiceEvent(**defaults)


def make_event_dict(**overrides: Any) -> dict[str, Any]:
    """Create a sample event as a raw dictionary (simulating bridge input)."""
    defaults = {
        "platform": "telegram",
        "user_id": "12345678",
        "chat_id": "-1001234567890",
        "message_id": "42",
        "timestamp": "2025-01-15T14:30:00Z",
        "audio_path": "/tmp/test_audio.ogg",
        "mime_type": "audio/ogg",
        "language_hint": "de",
    }
    defaults.update(overrides)
    return defaults


def make_transcript(text: str = "Ich hatte eine Idee für das neue Projekt.", **overrides: Any) -> TranscriptResult:
    """Create a sample TranscriptResult."""
    defaults = {
        "transcript": text,
        "detected_language": "de",
        "confidence": 0.92,
        "segments": [
            TranscriptSegment(start=0.0, end=3.5, text=text),
        ],
        "status": TranscriptStatus.SUCCESS,
    }
    defaults.update(overrides)
    return TranscriptResult(**defaults)


def make_intent(intent: Intent = Intent.CAPTURE_IDEA, **overrides: Any) -> IntentResult:
    """Create a sample IntentResult."""
    defaults = {
        "intent": intent,
        "confidence": 0.85,
        "title": "Project Idea",
        "summary": "An idea about a new project",
        "keywords": ["projekt", "idee"],
        "entities": {},
        "project": None,
        "action_items": [],
        "due_date": None,
        "priority": None,
        "suggested_tags": ["projekt"],
    }
    defaults.update(overrides)
    return IntentResult(**defaults)


def make_record(**overrides: Any) -> ProcessedRecord:
    """Create a fully populated ProcessedRecord for testing."""
    event = overrides.pop("event", make_event())
    transcript = overrides.pop("transcript", make_transcript())
    intent = overrides.pop("intent", make_intent())
    return ProcessedRecord(event=event, transcript=transcript, intent=intent)


# --- Sample transcripts for different intents ---

SAMPLE_TRANSCRIPTS: dict[str, str] = {
    "capture_idea_de": "Ich hatte gerade eine Idee für die neue App. Wir könnten eine Sprachsteuerung einbauen, die auf natürliche Befehle reagiert.",
    "capture_idea_zh": "我突然想到一个好主意，我们可以给应用加一个语音控制功能，让用户用自然语言来操作。",
    "task_de": "Ich muss morgen das Projektmeeting vorbereiten und die Präsentation aktualisieren.",
    "task_zh": "明天我要准备项目会议的资料，还要更新演示文稿，别忘了。",
    "journal_de": "Heute fühle ich mich sehr produktiv. Die Arbeit am Frontend macht Spaß, aber ich bin auch etwas müde.",
    "journal_zh": "今天心情不错，工作进展顺利。前端开发挺有意思的，但有点累了。",
    "knowledge_de": "Ich habe heute gelernt, dass Python 3.12 neue Syntax für Typ-Annotationen hat.",
    "knowledge_zh": "今天学到了一个知识点，Python 3.12 引入了新的类型注解语法。",
    "reminder_de": "Erinnere mich daran, am Freitag um 15 Uhr den Bericht abzuschicken.",
    "reminder_zh": "提醒我周五下午三点之前把报告发出去。",
}
