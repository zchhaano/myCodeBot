from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class ChatMessage:
    id: str
    chat_id: int
    role: str
    source: str
    text: str
    created_at: str


class ChatLogStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, list[ChatMessage]] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        data: dict[str, list[ChatMessage]] = {}
        for chat_id, items in raw.items():
            if not str(chat_id).lstrip("-").isdigit() or not isinstance(items, list):
                continue
            parsed: list[ChatMessage] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                try:
                    parsed.append(ChatMessage(**item))
                except TypeError:
                    continue
            if parsed:
                data[str(chat_id)] = parsed
        self._data = data

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            chat_id: [asdict(item) for item in items]
            for chat_id, items in sorted(self._data.items(), key=lambda item: int(item[0]))
        }
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def append(self, *, chat_id: int, role: str, source: str, text: str) -> ChatMessage:
        clean = text.strip()
        if not clean:
            raise ValueError("Chat message text must not be empty")

        message = ChatMessage(
            id=uuid.uuid4().hex,
            chat_id=chat_id,
            role=role,
            source=source,
            text=clean,
            created_at=_utc_now_iso(),
        )
        with self._lock:
            bucket = self._data.setdefault(str(chat_id), [])
            bucket.append(message)
            self._save()
        return message

    def items(self, chat_id: int, *, limit: int = 200) -> list[ChatMessage]:
        with self._lock:
            bucket = list(self._data.get(str(chat_id), []))
        if limit <= 0:
            return bucket
        return bucket[-limit:]

    def chat_ids(self) -> list[int]:
        with self._lock:
            return sorted(int(chat_id) for chat_id in self._data)
