"""Data models and event schema for voice-bridge-obsidian."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Intent(str, Enum):
    """Voice message intent categories."""
    CAPTURE_IDEA = "capture_idea"
    TASK = "task"
    JOURNAL = "journal"
    PROJECT_UPDATE = "project_update"
    MEETING_NOTE = "meeting_note"
    KNOWLEDGE = "knowledge"
    REMINDER_REQUEST = "reminder_request"
    COMMAND_REQUEST = "command_request"
    UNKNOWN = "unknown"


class TranscriptStatus(str, Enum):
    """Transcription outcome."""
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


class Priority(str, Enum):
    """Priority levels for tasks and reminders."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Platform(str, Enum):
    """Supported bridge platforms."""
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"


@dataclass
class VoiceEvent:
    """Incoming voice message event from bridge service.

    Required fields: platform, user_id, chat_id, message_id, timestamp, audio_path, mime_type
    Optional fields: language_hint, text_caption, contact_name
    """
    platform: Platform
    user_id: str
    chat_id: str
    message_id: str
    timestamp: str
    audio_path: str
    mime_type: str
    language_hint: str | None = None
    text_caption: str | None = None
    contact_name: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VoiceEvent:
        """Create VoiceEvent from a dictionary, with validation."""
        required = ["platform", "user_id", "chat_id", "message_id",
                     "timestamp", "audio_path", "mime_type"]
        missing = [f for f in required if f not in data]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")

        if data["platform"] not in ("telegram", "whatsapp"):
            raise ValueError(f"Unsupported platform: {data['platform']}. Must be 'telegram' or 'whatsapp'")

        return cls(
            platform=Platform(data["platform"]),
            user_id=str(data["user_id"]),
            chat_id=str(data["chat_id"]),
            message_id=str(data["message_id"]),
            timestamp=data["timestamp"],
            audio_path=data["audio_path"],
            mime_type=data["mime_type"],
            language_hint=data.get("language_hint"),
            text_caption=data.get("text_caption"),
            contact_name=data.get("contact_name"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "platform": self.platform.value,
            "user_id": self.user_id,
            "chat_id": self.chat_id,
            "message_id": self.message_id,
            "timestamp": self.timestamp,
            "audio_path": self.audio_path,
            "mime_type": self.mime_type,
            "language_hint": self.language_hint,
            "text_caption": self.text_caption,
            "contact_name": self.contact_name,
        }


@dataclass
class TranscriptSegment:
    """A single segment of transcribed audio."""
    start: float
    end: float
    text: str


@dataclass
class TranscriptResult:
    """Output from STT transcription."""
    transcript: str
    detected_language: str
    confidence: float | None = None
    segments: list[TranscriptSegment] = field(default_factory=list)
    status: TranscriptStatus = TranscriptStatus.SUCCESS

    def to_dict(self) -> dict[str, Any]:
        return {
            "transcript": self.transcript,
            "detected_language": self.detected_language,
            "confidence": self.confidence,
            "segments": [
                {"start": s.start, "end": s.end, "text": s.text}
                for s in self.segments
            ],
            "status": self.status.value,
        }

    @classmethod
    def failed(cls, reason: str) -> TranscriptResult:
        """Create a failed transcript result."""
        return cls(
            transcript="",
            detected_language="unknown",
            confidence=0.0,
            status=TranscriptStatus.FAILED,
        )


@dataclass
class IntentResult:
    """Output from intent classification."""
    intent: Intent
    confidence: float
    title: str | None = None
    summary: str | None = None
    keywords: list[str] = field(default_factory=list)
    entities: dict[str, list[str]] = field(default_factory=dict)
    project: str | None = None
    action_items: list[str] = field(default_factory=list)
    due_date: str | None = None
    priority: Priority | None = None
    suggested_tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "intent": self.intent.value,
            "confidence": self.confidence,
            "keywords": self.keywords,
            "entities": self.entities,
            "suggested_tags": self.suggested_tags,
            "action_items": self.action_items,
        }
        for key in ("title", "summary", "project", "due_date"):
            val = getattr(self, key)
            if val is not None:
                result[key] = val
        if self.priority is not None:
            result["priority"] = self.priority.value
        return result


@dataclass
class ProcessedRecord:
    """Complete processing result for a voice event."""
    event: VoiceEvent
    transcript: TranscriptResult
    intent: IntentResult
    processed_at: str = field(
        default_factory=lambda: datetime.now().isoformat()
    )

    def to_frontmatter(self) -> dict[str, Any]:
        """Generate YAML frontmatter for Obsidian note."""
        return {
            "source_platform": self.event.platform.value,
            "source_user": self.event.contact_name or self.event.user_id,
            "timestamp": self.event.timestamp,
            "intent": self.intent.intent.value,
            "tags": ["voice", self.intent.intent.value]
                    + self.intent.suggested_tags
                    + [self.transcript.detected_language],
            "project": self.intent.project,
            "audio_file": self.event.audio_path,
            "transcript_status": self.transcript.status.value,
            "processed_at": self.processed_at,
            "keywords": self.intent.keywords,
            "priority": self.intent.priority.value if self.intent.priority else None,
            "due_date": self.intent.due_date,
        }
