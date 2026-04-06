"""Unit tests for the voice-bridge-obsidian ingest pipeline."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

# Add scripts dir for imports
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from models import (
    Intent,
    IntentResult,
    Platform,
    Priority,
    TranscriptResult,
    TranscriptStatus,
    VoiceEvent,
)
from config_loader import Config
from test_fixtures import (
    SAMPLE_TRANSCRIPTS,
    make_event,
    make_event_dict,
    make_intent,
    make_record,
    make_transcript,
)


# --- Event Validation Tests ---

class TestVoiceEvent:
    def test_valid_event_from_dict(self) -> None:
        data = make_event_dict()
        event = VoiceEvent.from_dict(data)
        assert event.platform == Platform.TELEGRAM
        assert event.user_id == "12345678"
        assert event.contact_name is None

    def test_event_with_optional_fields(self) -> None:
        data = make_event_dict(
            language_hint="zh",
            text_caption="项目会议",
            contact_name="张三",
        )
        event = VoiceEvent.from_dict(data)
        assert event.language_hint == "zh"
        assert event.contact_name == "张三"

    def test_missing_required_field(self) -> None:
        data = make_event_dict()
        del data["audio_path"]
        with pytest.raises(ValueError, match="Missing required fields"):
            VoiceEvent.from_dict(data)

    def test_missing_multiple_fields(self) -> None:
        data = {"platform": "telegram"}
        with pytest.raises(ValueError, match="Missing required fields"):
            VoiceEvent.from_dict(data)

    def test_invalid_platform(self) -> None:
        data = make_event_dict(platform="signal")
        with pytest.raises(ValueError, match="Unsupported platform"):
            VoiceEvent.from_dict(data)

    def test_whatsapp_platform(self) -> None:
        data = make_event_dict(platform="whatsapp")
        event = VoiceEvent.from_dict(data)
        assert event.platform == Platform.WHATSAPP


# --- Transcript Tests ---

class TestTranscript:
    def test_successful_transcript(self) -> None:
        t = make_transcript()
        assert t.status == TranscriptStatus.SUCCESS
        assert len(t.segments) == 1
        assert t.detected_language == "de"

    def test_failed_transcript(self) -> None:
        t = TranscriptResult.failed("audio not found")
        assert t.status == TranscriptStatus.FAILED
        assert t.transcript == ""

    def test_transcript_serialization(self) -> None:
        t = make_transcript()
        d = t.to_dict()
        assert "transcript" in d
        assert "segments" in d
        assert d["status"] == "success"


# --- Intent Classification Tests ---

class TestIntentClassification:
    def test_local_keyword_match_idea_de(self) -> None:
        from intent_router import classify_local
        config = Config.load(None)
        patterns = config.get("intent.keyword_patterns", {})
        text = SAMPLE_TRANSCRIPTS["capture_idea_de"]
        result = classify_local(text, patterns)
        assert result.intent == Intent.CAPTURE_IDEA

    def test_local_keyword_match_task_de(self) -> None:
        from intent_router import classify_local
        config = Config.load(None)
        patterns = config.get("intent.keyword_patterns", {})
        text = SAMPLE_TRANSCRIPTS["task_de"]
        result = classify_local(text, patterns)
        assert result.intent == Intent.TASK

    def test_local_keyword_match_zh(self) -> None:
        from intent_router import classify_local
        config = Config.load(None)
        patterns = config.get("intent.keyword_patterns", {})
        text = SAMPLE_TRANSCRIPTS["capture_idea_zh"]
        result = classify_local(text, patterns)
        assert result.intent == Intent.CAPTURE_IDEA

    def test_unknown_intent(self) -> None:
        from intent_router import classify_local
        text = "The weather is sunny today and I went for a walk."
        result = classify_local(text, {})
        assert result.intent == Intent.UNKNOWN


# --- Priority and Due Date Extraction ---

class TestExtraction:
    def test_priority_high_de(self) -> None:
        from intent_router import _extract_priority
        assert _extract_priority("Das ist dringend!") == Priority.HIGH

    def test_priority_high_zh(self) -> None:
        from intent_router import _extract_priority
        assert _extract_priority("这个很紧急") == Priority.HIGH

    def test_priority_none(self) -> None:
        from intent_router import _extract_priority
        assert _extract_priority("Hello world") is None

    def test_due_date_tomorrow_de(self) -> None:
        from intent_router import _extract_due_date
        from datetime import date, timedelta
        result = _extract_due_date("Ich muss das morgen erledigen")
        expected = (date.today() + timedelta(days=1)).isoformat()
        assert result == expected

    def test_due_date_tomorrow_zh(self) -> None:
        from intent_router import _extract_due_date
        from datetime import date, timedelta
        result = _extract_due_date("明天要做这个")
        expected = (date.today() + timedelta(days=1)).isoformat()
        assert result == expected


# --- Config Tests ---

class TestConfig:
    def test_default_config(self) -> None:
        config = Config.load(None)
        assert config.stt_adapter == "faster_whisper"
        assert config.stt_model == "large-v3"
        assert config.obsidian_method == "file"

    def test_dotpath_access(self) -> None:
        config = Config.load(None)
        assert config.get("stt.device") == "cpu"
        assert config.get("nonexistent.key", "default") == "default"

    def test_env_override(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("STT_DEVICE", "cuda")
        config = Config.load(None)
        assert config.stt_device == "cuda"

    def test_validate_missing_vault(self) -> None:
        config = Config.load(None)
        issues = config.validate()
        assert any("Vault path" in issue for issue in issues)

    def test_load_or_bootstrap_creates_config_from_example(self, tmp_path: Any) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        example = config_dir / "settings.example.yaml"
        example.write_text(
            "vault:\n  path: /path/to/your/obsidian/vault\nstt:\n  adapter: faster_whisper\n",
            encoding="utf-8",
        )

        config = Config.load_or_bootstrap(config_dir / "settings.yaml", interactive=False)

        assert (config_dir / "settings.yaml").exists()
        assert str(config.vault_path) == "/path/to/your/obsidian/vault"

    def test_load_or_bootstrap_prompts_for_vault_path(self, tmp_path: Any, monkeypatch: Any) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_path = config_dir / "settings.yaml"
        config_path.write_text(
            "vault:\n  path: /path/to/your/obsidian/vault\n",
            encoding="utf-8",
        )

        vault_dir = tmp_path / "MyVault"
        vault_dir.mkdir()
        monkeypatch.setattr("builtins.input", lambda _: str(vault_dir))

        config = Config.load_or_bootstrap(config_path, interactive=True)

        assert config.vault_path == vault_dir.resolve()
        assert str(vault_dir.resolve()) in config_path.read_text(encoding="utf-8")


# --- Obsidian Store Tests (using temp dir) ---

class TestObsidianStore:
    def _make_config(self, tmpdir: Path) -> Config:
        """Create a Config with a temporary vault path."""
        config = Config.load(None)
        config._data["vault"]["path"] = str(tmpdir)
        return config

    def test_write_note_creates_file(self, tmp_path: Any) -> None:
        from obsidian_store import ObsidianStore
        config = self._make_config(tmp_path)
        store = ObsidianStore(config)
        record = make_record()
        path = store.write_note(record)
        assert path.exists()
        content = path.read_text()
        assert "Voice Note" in content

    def test_append_daily(self, tmp_path: Any) -> None:
        from obsidian_store import ObsidianStore
        config = self._make_config(tmp_path)
        store = ObsidianStore(config)
        record = make_record()
        path = store.append_daily(record)
        assert path is not None
        assert path.exists()

    def test_write_to_project(self, tmp_path: Any) -> None:
        from obsidian_store import ObsidianStore
        config = self._make_config(tmp_path)
        store = ObsidianStore(config)
        intent = make_intent(project="my-project")
        record = make_record(intent=intent)
        path = store.write_to_project(record)
        assert path is not None
        assert "my-project" in str(path)

    def test_write_pending_reminder(self, tmp_path: Any) -> None:
        from obsidian_store import ObsidianStore
        config = self._make_config(tmp_path)
        store = ObsidianStore(config)
        record = make_record()
        path = store.write_pending(record, "reminders", note="Test reminder")
        assert path.exists()
        content = path.read_text()
        assert "Test reminder" in content


# --- Action Executor Tests ---

class TestActionExecutor:
    def _make_config(self, tmpdir: Path) -> Config:
        config = Config.load(None)
        config._data["vault"]["path"] = str(tmpdir)
        return config

    def test_execute_writes_inbox_and_daily(self, tmp_path: Any) -> None:
        from action_executor import ActionExecutor
        from obsidian_store import ObsidianStore
        config = self._make_config(tmp_path)
        store = ObsidianStore(config)
        executor = ActionExecutor(config, store)
        record = make_record()
        results = executor.execute(record)
        assert any("wrote_inbox" in a for a in results["actions_taken"])

    def test_reminder_goes_to_pending(self, tmp_path: Any) -> None:
        from action_executor import ActionExecutor
        from obsidian_store import ObsidianStore
        config = self._make_config(tmp_path)
        store = ObsidianStore(config)
        executor = ActionExecutor(config, store)
        intent = make_intent(intent=Intent.REMINDER_REQUEST, due_date="2025-01-20")
        record = make_record(intent=intent)
        results = executor.execute(record)
        assert any(p["type"] == "reminder" for p in results["pending"])

    def test_command_goes_to_pending(self, tmp_path: Any) -> None:
        from action_executor import ActionExecutor
        from obsidian_store import ObsidianStore
        config = self._make_config(tmp_path)
        store = ObsidianStore(config)
        executor = ActionExecutor(config, store)
        intent = make_intent(intent=Intent.COMMAND_REQUEST)
        record = make_record(intent=intent)
        results = executor.execute(record)
        assert any(p["type"] == "command" for p in results["pending"])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
