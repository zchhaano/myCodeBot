from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from channel_keys import DEFAULT_CHANNEL, make_conversation_key, parse_conversation_key


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class ChatMessage:
    id: str
    conversation_key: str
    channel: str
    chat_id: str
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
            conversation_key = self._normalize_key(chat_id)
            if not isinstance(items, list):
                continue
            parsed: list[ChatMessage] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                try:
                    if "conversation_key" not in item:
                        ref = parse_conversation_key(conversation_key)
                        item = {
                            **item,
                            "conversation_key": conversation_key,
                            "channel": ref.channel,
                            "chat_id": ref.chat_id,
                        }
                    parsed.append(ChatMessage(**item))
                except TypeError:
                    continue
            if parsed:
                data[conversation_key] = parsed
        self._data = data

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            chat_id: [asdict(item) for item in items]
            for chat_id, items in sorted(self._data.items(), key=lambda item: item[0])
        }
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def append(
        self,
        *,
        chat_id: str | int,
        role: str,
        source: str,
        text: str,
        channel: str = DEFAULT_CHANNEL,
    ) -> ChatMessage:
        clean = text.strip()
        if not clean:
            raise ValueError("Chat message text must not be empty")

        conversation_key = self._normalize_key(chat_id, channel=channel)
        ref = parse_conversation_key(conversation_key)
        message = ChatMessage(
            id=uuid.uuid4().hex,
            conversation_key=conversation_key,
            channel=ref.channel,
            chat_id=ref.chat_id,
            role=role,
            source=source,
            text=clean,
            created_at=_utc_now_iso(),
        )
        with self._lock:
            bucket = self._data.setdefault(conversation_key, [])
            bucket.append(message)
            self._save()
        return message

    def items(self, chat_id: str | int, *, limit: int = 200, channel: str = DEFAULT_CHANNEL) -> list[ChatMessage]:
        with self._lock:
            bucket = list(self._data.get(self._normalize_key(chat_id, channel=channel), []))
        if limit <= 0:
            return bucket
        return bucket[-limit:]

    def chat_ids(self, *, channel: str = DEFAULT_CHANNEL) -> list[str]:
        with self._lock:
            return sorted(
                message.chat_id
                for key, items in self._data.items()
                for message in items[:1]
                if parse_conversation_key(key).channel == channel
            )

    def conversation_keys(self) -> list[str]:
        with self._lock:
            return sorted(self._data)

    @staticmethod
    def _normalize_key(chat_id: str | int, *, channel: str = DEFAULT_CHANNEL) -> str:
        raw = str(chat_id).strip()
        if ":" in raw:
            return raw
        return make_conversation_key(channel, raw)
