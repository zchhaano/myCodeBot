"""Configuration loading and validation for voice-bridge-obsidian."""

from __future__ import annotations

import os
import shutil
import sys
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


def _default_config_candidates(base_dir: Path | None = None) -> list[Path]:
    skill_root = base_dir or Path(__file__).resolve().parent.parent
    return [
        skill_root / "config" / "settings.yaml",
        Path.cwd() / "config" / "settings.yaml",
    ]


def _example_config_for(config_path: Path) -> Path:
    return config_path.with_name("settings.example.yaml")


def _normalize_vault_path(raw: str) -> Path:
    return Path(raw).expanduser().resolve()


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

    @classmethod
    def load_or_bootstrap(
        cls,
        config_path: str | Path | None = None,
        *,
        interactive: bool | None = None,
    ) -> Config:
        """Load config and guide the user through first-run setup when possible."""
        resolved_path = cls._resolve_config_path(config_path)
        should_prompt = interactive if interactive is not None else (
            sys.stdin.isatty() and sys.stdout.isatty()
        )

        if resolved_path and not resolved_path.exists():
            example_path = _example_config_for(resolved_path)
            if example_path.exists():
                resolved_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(example_path, resolved_path)
                print(
                    f"Created config from template: {resolved_path}",
                    file=sys.stderr,
                )

        config = cls.load(resolved_path)

        if should_prompt and not os.getenv("OBSIDIAN_VAULT_PATH"):
            prompted = cls._prompt_for_vault_path(config, resolved_path)
            if prompted is not None:
                config = cls.load(resolved_path)

        return config

    @staticmethod
    def _resolve_config_path(config_path: str | Path | None) -> Path | None:
        if config_path is not None:
            return Path(config_path).expanduser().resolve()
        for candidate in _default_config_candidates():
            if candidate.exists():
                return candidate.resolve()
        return _default_config_candidates()[0].resolve()

    @classmethod
    def _prompt_for_vault_path(cls, config: Config, config_path: Path | None) -> Path | None:
        current = str(config.get("vault.path", "") or "").strip()
        current_path = Path(current).expanduser() if current else None
        needs_prompt = (
            not current
            or current == "/path/to/your/obsidian/vault"
            or current_path is None
            or not current_path.exists()
        )
        if not needs_prompt:
            return None

        print(
            "Voice Bridge Obsidian first-run setup:",
            file=sys.stderr,
        )
        if current:
            print(
                f"Configured vault path is missing or invalid: {current}",
                file=sys.stderr,
            )
        prompt = "Enter your Obsidian vault path: "
        while True:
            raw = input(prompt).strip()
            if not raw:
                print("Vault path is required.", file=sys.stderr)
                continue
            candidate = _normalize_vault_path(raw)
            if not candidate.exists():
                print(f"Path does not exist: {candidate}", file=sys.stderr)
                continue
            if not candidate.is_dir():
                print(f"Path is not a directory: {candidate}", file=sys.stderr)
                continue
            if config_path is not None:
                cls._write_vault_path(config_path, candidate)
                print(
                    f"Saved vault path to {config_path}",
                    file=sys.stderr,
                )
            return candidate

    @staticmethod
    def _write_vault_path(config_path: Path, vault_path: Path) -> None:
        payload: dict[str, Any] = {}
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as handle:
                payload = yaml.safe_load(handle) or {}
        vault = payload.setdefault("vault", {})
        vault["path"] = str(vault_path)
        with open(config_path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)

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
