from __future__ import annotations

from dataclasses import dataclass

DEFAULT_CHANNEL = "telegram"


@dataclass(frozen=True)
class ConversationRef:
    channel: str
    chat_id: str

    @property
    def key(self) -> str:
        return make_conversation_key(self.channel, self.chat_id)


def normalize_channel(value: str | None) -> str:
    clean = (value or DEFAULT_CHANNEL).strip().lower()
    return clean or DEFAULT_CHANNEL


def normalize_chat_id(value: str | int) -> str:
    return str(value).strip()


def make_conversation_key(channel: str, chat_id: str | int) -> str:
    return f"{normalize_channel(channel)}:{normalize_chat_id(chat_id)}"


def parse_conversation_key(value: str | int, *, default_channel: str = DEFAULT_CHANNEL) -> ConversationRef:
    raw = str(value).strip()
    if not raw:
        return ConversationRef(channel=normalize_channel(default_channel), chat_id="")
    if ":" not in raw:
        return ConversationRef(channel=normalize_channel(default_channel), chat_id=raw)
    channel, chat_id = raw.split(":", 1)
    return ConversationRef(channel=normalize_channel(channel), chat_id=normalize_chat_id(chat_id))


def conversation_key_for_legacy_chat(chat_id: str | int) -> str:
    return make_conversation_key(DEFAULT_CHANNEL, chat_id)
