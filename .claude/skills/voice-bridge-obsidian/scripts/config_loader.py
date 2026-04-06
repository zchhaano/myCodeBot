"""Configuration loading and validation for voice-bridge-obsidian."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


_DEFAULTS: dict[str, Any] = {
    "vault": {
        "path": "",
        "folders": {
            "inbox": "Inbox/Voice",
            "daily": "Daily",
            "projects": "Projects",
            "summaries_daily": "Summaries/Daily",
            "summaries_weekly": "Summaries/Weekly",
            "pending": "Pending",
        },
    },
    "stt": {
        "adapter": "faster_whisper",
        "model": "large-v3",
        "device": "cpu",
        "compute_type": "int8",
        "language": None,
    },
    "intent": {
        "confidence_threshold": 0.5,
        "use_claude": False,
        "claude_model": "claude-sonnet-4-20250514",
        "keyword_patterns": {
            "capture_idea": [
                "idee", "想法", "灵感", "gedanke", "突然想到",
                "es wäre cool", "想想", "突然觉得", "点子",
            ],
            "task": [
                "aufgabe", "todo", "待办", "要做的", "muss ich",
                "别忘了", "记得", "要做", "任务", "erledigen",
            ],
            "journal": [
                "tagebuch", "日记", "heute fühle", "今天的心情",
                "反思", "gefühl", "心情", "随笔", "随笔",
            ],
            "project_update": [
                "projekt", "项目", "fortschritt", "进展", "status",
                "sprint", "里程碑", "meilenstein",
            ],
            "meeting_note": [
                "meeting", "会议", "besprechung", "call", "通话",
                "讨论", "diskussion", "standup", "开会",
            ],
            "knowledge": [
                "wissen", "知识", "gelernt", "学到", "摘录",
                "notiz", "笔记", "tip", "技巧", "trick",
            ],
            "reminder_request": [
                "erinnere", "提醒", "um", "之前", "定时",
                "记得", "vergiss nicht", "别忘了", "提醒我",
            ],
            "command_request": [
                "führe aus", "执行", "starte", "启动",
                "öffne", "打开", "帮我", "hilfe",
            ],
        },
    },
    "actions": {
        "safe_mode": False,
        "allowed_commands": [],
        "blocked_patterns": [],
    },
    "obsidian": {
        "method": "file",
    },
    "logging": {
        "level": "INFO",
        "dir": "logs",
        "file_pattern": "voice-bridge-{year}-{month}-{day}.log",
        "max_size_mb": 10,
        "backup_count": 5,
    },
    "digest": {
        "daily_time": "22:00",
        "weekly_day": "sunday",
        "weekly_time": "21:30",
        "include_audio_links": False,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    result = base.copy()
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


class Config:
    """Application configuration loaded from YAML with env var overrides."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> Config:
        """Load config from YAML file, falling back to defaults.

        Environment variables override YAML values:
          OBSIDIAN_VAULT_PATH → vault.path
          STT_ADAPTER → stt.adapter
          STT_MODEL → stt.model
          STT_DEVICE → stt.device
          LOG_LEVEL → logging.level
          SAFE_MODE → actions.safe_mode (parse as bool)
        """
        data = _DEFAULTS.copy()

        if config_path and Path(config_path).exists():
            with open(config_path, "r", encoding="utf-8") as f:
                file_data = yaml.safe_load(f) or {}
            data = _deep_merge(data, file_data)

        # Environment variable overrides
        if vault_path := os.getenv("OBSIDIAN_VAULT_PATH"):
            data["vault"]["path"] = vault_path
        if stt_adapter := os.getenv("STT_ADAPTER"):
            data["stt"]["adapter"] = stt_adapter
        if stt_model := os.getenv("STT_MODEL"):
            data["stt"]["model"] = stt_model
        if stt_device := os.getenv("STT_DEVICE"):
            data["stt"]["device"] = stt_device
        if log_level := os.getenv("LOG_LEVEL"):
            data["logging"]["level"] = log_level
        if safe_mode := os.getenv("SAFE_MODE"):
            data["actions"]["safe_mode"] = safe_mode.lower() in ("true", "1", "yes")

        return cls(data)

    def get(self, dotpath: str, default: Any = None) -> Any:
        """Get a nested config value using dot notation.

        Example: config.get("vault.path")
        """
        keys = dotpath.split(".")
        val = self._data
        for key in keys:
            if isinstance(val, dict) and key in val:
                val = val[key]
            else:
                return default
        return val

    @property
    def vault_path(self) -> Path:
        return Path(self.get("vault.path", ""))

    @property
    def folders(self) -> dict[str, str]:
        return self.get("vault.folders", {})

    def folder_path(self, key: str) -> Path:
        """Get absolute path for a vault folder."""
        return self.vault_path / self.folders.get(key, key)

    @property
    def stt_adapter(self) -> str:
        return self.get("stt.adapter", "faster_whisper")

    @property
    def stt_model(self) -> str:
        return self.get("stt.model", "large-v3")

    @property
    def stt_device(self) -> str:
        return self.get("stt.device", "cpu")

    @property
    def safe_mode(self) -> bool:
        return self.get("actions.safe_mode", False)

    @property
    def obsidian_method(self) -> str:
        return self.get("obsidian.method", "file")

    def validate(self) -> list[str]:
        """Validate configuration, returning list of issues."""
        issues: list[str] = []
        if not self.vault_path or not self.vault_path.exists():
            issues.append(f"Vault path does not exist: {self.vault_path}")
        if self.stt_adapter not in ("faster_whisper", "whisper", "custom"):
            issues.append(f"Unknown STT adapter: {self.stt_adapter}")
        return issues
