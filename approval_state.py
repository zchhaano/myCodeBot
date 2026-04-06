from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from channel_keys import DEFAULT_CHANNEL, make_conversation_key, parse_conversation_key


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class PendingApproval:
    conversation_key: str
    channel: str
    chat_id: str
    session_id: str | None
    cwd: str
    original_prompt: str
    permission_mode: str
    requested_at: str
    assistant_message: str


class ApprovalState:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._pending: dict[str, PendingApproval] = {}
        self._always: dict[str, str] = {}
        self._last_auto_request: dict[str, tuple[str, int]] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        always = raw.get("always") or {}
        self._always = {
            self._normalize_key(chat_id): str(mode)
            for chat_id, mode in always.items()
            if str(mode).strip()
        }

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "always": {chat_id: mode for chat_id, mode in sorted(self._always.items())},
        }
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def get(self, chat_id: str | int, *, channel: str = DEFAULT_CHANNEL) -> PendingApproval | None:
        with self._lock:
            return self._pending.get(self._normalize_key(chat_id, channel=channel))

    def set(
        self,
        *,
        chat_id: str | int,
        session_id: str | None,
        cwd: str,
        original_prompt: str,
        permission_mode: str,
        assistant_message: str,
        channel: str = DEFAULT_CHANNEL,
    ) -> PendingApproval:
        conversation_key = self._normalize_key(chat_id, channel=channel)
        ref = parse_conversation_key(conversation_key)
        approval = PendingApproval(
            conversation_key=conversation_key,
            channel=ref.channel,
            chat_id=ref.chat_id,
            session_id=session_id,
            cwd=cwd,
            original_prompt=original_prompt,
            permission_mode=permission_mode,
            requested_at=_utc_now_iso(),
            assistant_message=assistant_message,
        )
        with self._lock:
            self._pending[conversation_key] = approval
        return approval

    def pop(self, chat_id: str | int, *, channel: str = DEFAULT_CHANNEL) -> PendingApproval | None:
        with self._lock:
            return self._pending.pop(self._normalize_key(chat_id, channel=channel), None)

    def clear(self, chat_id: str | int, *, channel: str = DEFAULT_CHANNEL) -> bool:
        with self._lock:
            key = self._normalize_key(chat_id, channel=channel)
            self._last_auto_request.pop(key, None)
            return self._pending.pop(key, None) is not None

    def count(self) -> int:
        with self._lock:
            return len(self._pending)

    def get_always_mode(self, chat_id: str | int, *, channel: str = DEFAULT_CHANNEL) -> str | None:
        with self._lock:
            return self._always.get(self._normalize_key(chat_id, channel=channel))

    def set_always_mode(self, chat_id: str | int, permission_mode: str, *, channel: str = DEFAULT_CHANNEL) -> None:
        with self._lock:
            key = self._normalize_key(chat_id, channel=channel)
            self._always[key] = permission_mode
            self._last_auto_request.pop(key, None)
            self._save()

    def clear_always_mode(self, chat_id: str | int, *, channel: str = DEFAULT_CHANNEL) -> bool:
        with self._lock:
            key = self._normalize_key(chat_id, channel=channel)
            removed = self._always.pop(key, None)
            self._last_auto_request.pop(key, None)
            if removed is None:
                return False
            self._save()
            return True

    def always_count(self) -> int:
        with self._lock:
            return len(self._always)

    def record_auto_request(self, chat_id: str | int, fingerprint: str, *, channel: str = DEFAULT_CHANNEL) -> int:
        with self._lock:
            key = self._normalize_key(chat_id, channel=channel)
            last_fingerprint, last_count = self._last_auto_request.get(key, ("", 0))
            if last_fingerprint == fingerprint:
                next_count = last_count + 1
            else:
                next_count = 1
            self._last_auto_request[key] = (fingerprint, next_count)
            return next_count

    def reset_auto_request(self, chat_id: str | int, *, channel: str = DEFAULT_CHANNEL) -> None:
        with self._lock:
            self._last_auto_request.pop(self._normalize_key(chat_id, channel=channel), None)

    @staticmethod
    def _normalize_key(chat_id: str | int, *, channel: str = DEFAULT_CHANNEL) -> str:
        raw = str(chat_id).strip()
        if ":" in raw:
            return raw
        return make_conversation_key(channel, raw)
