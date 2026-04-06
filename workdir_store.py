from __future__ import annotations

import json
import threading
from pathlib import Path

from channel_keys import DEFAULT_CHANNEL, make_conversation_key


class WorkdirStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        self._data = {
            self._normalize_key(str(key)): str(value)
            for key, value in raw.items()
            if str(value).strip()
        }

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {key: self._data[key] for key in sorted(self._data)}
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def get(self, chat_id: str | int, *, channel: str = DEFAULT_CHANNEL) -> str | None:
        with self._lock:
            return self._data.get(self._normalize_key(chat_id, channel=channel))

    def set(self, chat_id: str | int, cwd: str, *, channel: str = DEFAULT_CHANNEL) -> None:
        with self._lock:
            self._data[self._normalize_key(chat_id, channel=channel)] = cwd
            self._save()

    def clear(self, chat_id: str | int, *, channel: str = DEFAULT_CHANNEL) -> bool:
        with self._lock:
            removed = self._data.pop(self._normalize_key(chat_id, channel=channel), None)
            if removed is None:
                return False
            self._save()
            return True

    def items(self) -> list[tuple[str, str]]:
        with self._lock:
            return sorted(self._data.items(), key=lambda item: item[0])

    @staticmethod
    def _normalize_key(chat_id: str | int, *, channel: str = DEFAULT_CHANNEL) -> str:
        raw = str(chat_id).strip()
        if ":" in raw:
            return raw
        return make_conversation_key(channel, raw)
