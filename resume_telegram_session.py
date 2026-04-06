from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

from channel_keys import DEFAULT_CHANNEL, parse_conversation_key
from config import Settings, _build_settings
from session_store import SessionStore, SessionRecord


CONFIG_DIR = Path.home() / ".config" / "telegram-claude-bridge"
DEFAULT_ENV_PATH = CONFIG_DIR / "env"
DEFAULT_BOTS_PATH = CONFIG_DIR / "bots.json"


@dataclass(frozen=True)
class ResumeTarget:
    settings: Settings
    chat_id: str
    record: SessionRecord
    command: list[str]


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] == value[-1:] and value[:1] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def _load_runtime_settings() -> list[Settings]:
    file_values = _parse_env_file(DEFAULT_ENV_PATH)
    base_values = file_values.copy()
    base_values.update({key: value for key, value in os.environ.items() if value is not None})

    if DEFAULT_BOTS_PATH.exists():
        raw = json.loads(DEFAULT_BOTS_PATH.read_text(encoding="utf-8"))
        bot_items = raw.get("bots") if isinstance(raw, dict) else raw
        if not isinstance(bot_items, list) or not bot_items:
            raise RuntimeError(f"Invalid bots config: {DEFAULT_BOTS_PATH}")

        settings_list: list[Settings] = []
        config_base_dir = DEFAULT_BOTS_PATH.parent
        for index, item in enumerate(bot_items, start=1):
            if not isinstance(item, dict):
                raise RuntimeError(f"Bot config entry #{index} must be an object")

            item_values = {str(key): str(value) for key, value in item.items() if value is not None}
            merged = base_values.copy()
            merged.update(item_values)
            bot_name = merged.get("BRIDGE_NAME", "").strip() or f"bot{index}"
            bot_data_dir = config_base_dir / "data" / bot_name
            if "SESSION_STORE_PATH" not in item_values:
                merged["SESSION_STORE_PATH"] = str(bot_data_dir / "sessions.json")
            settings_list.append(_build_settings(merged, base_dir=config_base_dir, default_name=bot_name))
        return settings_list

    return [_build_settings(base_values, base_dir=CONFIG_DIR, default_name="default")]


def _select_settings(settings_list: list[Settings], *, bot_name: str | None, provider: str | None) -> Settings:
    if bot_name:
        for settings in settings_list:
            if settings.name == bot_name:
                return settings
        raise RuntimeError(f"Unknown bot name: {bot_name}")

    if provider:
        matches = [settings for settings in settings_list if settings.provider == provider]
        if not matches:
            raise RuntimeError(f"No configured bot for provider: {provider}")
        if len(matches) > 1:
            names = ", ".join(settings.name for settings in matches)
            raise RuntimeError(f"Multiple bots match provider {provider}: {names}. Use --bot.")
        return matches[0]

    if len(settings_list) == 1:
        return settings_list[0]

    names = ", ".join(f"{settings.name}({settings.provider})" for settings in settings_list)
    raise RuntimeError(f"Multiple bots configured: {names}. Use --bot or --provider.")


def get_resume_target(
    *,
    chat_id: str | int,
    bot_name: str | None = None,
    provider: str | None = None,
    settings_list: list[Settings] | None = None,
) -> ResumeTarget:
    resolved_settings = settings_list or _load_runtime_settings()
    settings = _select_settings(resolved_settings, bot_name=bot_name, provider=provider)
    store = SessionStore(settings.session_store_path)
    record = store.get(chat_id)
    if record is None:
        raise RuntimeError(
            f"No stored session for conversation={chat_id} in {settings.name} ({settings.provider})"
        )
    return ResumeTarget(
        settings=settings,
        chat_id=str(chat_id),
        record=record,
        command=_build_resume_command(settings, record),
    )


def get_resume_targets_for_chat(chat_id: str | int, settings_list: list[Settings] | None = None) -> list[ResumeTarget]:
    resolved_settings = settings_list or _load_runtime_settings()
    ref = parse_conversation_key(chat_id)
    targets: list[ResumeTarget] = []
    for settings in resolved_settings:
        store = SessionStore(settings.session_store_path)
        record = store.get(chat_id)
        if record is None and ref.channel == DEFAULT_CHANNEL:
            record = store.get(ref.chat_id)
        if record is None:
            continue
        targets.append(
            ResumeTarget(
                settings=settings,
                chat_id=str(chat_id),
                record=record,
                command=_build_resume_command(settings, record),
            )
        )
    return targets


def format_resume_target(target: ResumeTarget) -> str:
    return (
        f"bot: {target.settings.name}\n"
        f"provider: {target.settings.provider}\n"
        f"conversation: {target.chat_id}\n"
        f"session_id: {target.record.session_id}\n"
        f"cwd: {target.record.cwd}\n"
        f"command: {shlex.join(target.command)}"
    )


def _build_resume_command(settings: Settings, record: SessionRecord) -> list[str]:
    if settings.provider == "claude":
        command = [settings.claude_bin, "--resume", record.session_id]
        if settings.claude_settings_file:
            command.extend(["--settings", str(settings.claude_settings_file)])
        if settings.claude_permission_mode:
            command.extend(["--permission-mode", settings.claude_permission_mode])
        if settings.claude_allowed_tools:
            command.append("--allowedTools")
            command.extend(settings.claude_allowed_tools)
        if settings.claude_disallowed_tools:
            command.append("--disallowedTools")
            command.extend(settings.claude_disallowed_tools)
        return command

    if settings.provider == "codex":
        command = [settings.codex_bin, "resume", record.session_id, "-C", record.cwd]
        if settings.codex_model:
            command.extend(["-m", settings.codex_model])
        if settings.codex_sandbox:
            command.extend(["-s", settings.codex_sandbox])
        if settings.codex_approval_policy:
            command.extend(["-a", settings.codex_approval_policy])
        return command

    raise RuntimeError(f"Unsupported provider for interactive resume: {settings.provider}")


def _print_session_list(settings_list: list[Settings]) -> int:
    found = False
    for settings in settings_list:
        store = SessionStore(settings.session_store_path)
        items = store.items()
        if not items:
            continue
        found = True
        print(f"[{settings.name}] provider={settings.provider} sessions={settings.session_store_path}")
        for conversation_key, record in items:
            print(
                f"  conversation={conversation_key} session_id={record.session_id} "
                f"updated_at={record.updated_at} cwd={record.cwd}"
            )
    if not found:
        print("No stored bridge sessions found.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resume a bridge conversation in local Claude Code or Codex.",
    )
    parser.add_argument("--list", action="store_true", help="List known bridge conversations for all bots")
    parser.add_argument("--bot", help="Bridge bot name, e.g. claude_bot or codex_bot")
    parser.add_argument("--provider", choices=["claude", "codex", "copilot"], help="Select by provider")
    parser.add_argument("--chat-id", help="Conversation key to resume, e.g. telegram:12345 or whatsapp:491234")
    parser.add_argument("--exec", action="store_true", dest="exec_session", help="Exec into the interactive CLI")
    args = parser.parse_args()

    settings_list = _load_runtime_settings()

    if args.list:
        return _print_session_list(settings_list)

    if args.chat_id is None:
        parser.error("--chat-id is required unless --list is used")

    target = get_resume_target(
        chat_id=args.chat_id,
        bot_name=args.bot,
        provider=args.provider,
        settings_list=settings_list,
    )
    print(format_resume_target(target))

    if args.exec_session:
        os.chdir(target.record.cwd)
        os.execvp(target.command[0], target.command)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
