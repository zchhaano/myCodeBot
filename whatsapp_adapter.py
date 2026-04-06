from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from bridge_core import BridgeCore, SentMessage
from channel_keys import ConversationRef
from media_handler import MediaHandlerError


LOGGER = logging.getLogger("telegram-claude-bridge.whatsapp")


class WhatsAppAdapter:
    can_edit_messages = False

    def __init__(self, settings, core: BridgeCore) -> None:
        self._settings = settings
        self._core = core

    def help_channel_label(self) -> str:
        return "WhatsApp"

    def start(self) -> ThreadingHTTPServer:
        self._validate_config()
        handler_class = self._build_handler()
        server = ThreadingHTTPServer((self._settings.whatsapp_webhook_host, self._settings.whatsapp_webhook_port), handler_class)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        LOGGER.info(
            "Started WhatsApp webhook on http://%s:%s/whatsapp/webhook",
            self._settings.whatsapp_webhook_host,
            self._settings.whatsapp_webhook_port,
        )
        return server

    def send_message(self, conversation: ConversationRef, text: str, role: str = "system") -> SentMessage | None:
        payload = {
            "messaging_product": "whatsapp",
            "to": conversation.chat_id,
            "type": "text",
            "text": {"body": text[:4096]},
        }
        result = self._graph_post(f"/{self._settings.whatsapp_phone_number_id}/messages", payload)
        return SentMessage(message_id=None, raw=result)

    def edit_message(
        self,
        conversation: ConversationRef,
        message_id: str,
        text: str,
        role: str = "system",
    ) -> SentMessage | None:
        return None

    def _build_handler(self):
        adapter = self

        class WhatsAppHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path != "/whatsapp/webhook":
                    self.send_error(404, "Not Found")
                    return
                params = parse_qs(parsed.query)
                mode = (params.get("hub.mode") or [""])[0]
                token = (params.get("hub.verify_token") or [""])[0]
                challenge = (params.get("hub.challenge") or [""])[0]
                if mode == "subscribe" and token == (adapter._settings.whatsapp_verify_token or ""):
                    body = challenge.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_error(403, "Forbidden")

            def do_POST(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path != "/whatsapp/webhook":
                    self.send_error(404, "Not Found")
                    return
                length = int(self.headers.get("Content-Length", "0") or "0")
                raw = self.rfile.read(length) if length > 0 else b"{}"
                payload = json.loads(raw.decode("utf-8"))
                try:
                    adapter._handle_webhook(payload)
                except Exception:
                    LOGGER.exception("Failed to process WhatsApp webhook")
                body = b"OK"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
                LOGGER.info("%s - %s", self.address_string(), format % args)

        return WhatsAppHandler

    def _handle_webhook(self, payload: dict[str, Any]) -> None:
        for entry in payload.get("entry") or []:
            if not isinstance(entry, dict):
                continue
            for change in entry.get("changes") or []:
                if not isinstance(change, dict):
                    continue
                value = change.get("value") or {}
                messages = value.get("messages") or []
                for message in messages:
                    if not isinstance(message, dict):
                        continue
                    self._handle_message(message)

    def _handle_message(self, message: dict[str, Any]) -> None:
        sender = str(message.get("from") or "").strip()
        if not sender:
            return
        conversation = ConversationRef(channel="whatsapp", chat_id=sender)
        self._core._runtime_state.record_message()

        message_type = (message.get("type") or "").strip().lower()
        if message_type == "text":
            body = ((message.get("text") or {}).get("body") or "").strip()
            if body:
                self._core.process_text(conversation, body)
            return

        if message_type == "image":
            self._handle_image(conversation, message)
            return

        if message_type in {"audio", "voice"}:
            self._handle_audio(conversation, message)
            return

        self.send_message(conversation, "暂不支持这种 WhatsApp 消息类型。当前支持文本、图片和音频。")

    def _handle_image(self, conversation: ConversationRef, message: dict[str, Any]) -> None:
        image = message.get("image") or {}
        media_id = str(image.get("id") or "").strip()
        if not media_id:
            self.send_message(conversation, "WhatsApp 图片消息缺少 media id。")
            return
        caption = str(image.get("caption") or "").strip()
        self._core.log_message(
            conversation,
            role="user",
            source="whatsapp",
            text=caption or "[WhatsApp image]",
        )
        self.send_message(conversation, f"已收到 WhatsApp 图片，正在下载并转交给 {self._settings.provider}…")
        try:
            media = self._download_media(media_id=media_id, caption=caption, default_name=f"{media_id}.jpg")
            prompt = self._core._media_handler.build_image_prompt(media)
            self._core.run_prompt(
                conversation,
                prompt=prompt,
                start_text=None,
                image_paths=[str(media.path)] if self._settings.provider == "codex" else None,
            )
        except MediaHandlerError as exc:
            self.send_message(conversation, f"WhatsApp 图片处理失败:\n{exc}")

    def _handle_audio(self, conversation: ConversationRef, message: dict[str, Any]) -> None:
        audio = message.get("audio") or {}
        media_id = str(audio.get("id") or "").strip()
        if not media_id:
            self.send_message(conversation, "WhatsApp 音频消息缺少 media id。")
            return
        self._core.log_message(
            conversation,
            role="user",
            source="whatsapp",
            text="[WhatsApp audio]",
        )
        self.send_message(conversation, "已收到 WhatsApp 音频，正在下载并转写…")
        try:
            media = self._download_media(
                media_id=media_id,
                caption="",
                default_name=f"{media_id}.ogg",
            )
            transcript = self._core._media_handler.transcribe_voice(media)
            self._core.log_message(
                conversation,
                role="user",
                source="whatsapp",
                text=f"[Voice transcript]\n{transcript.text.strip() or '(empty transcription)'}",
            )
            self.send_message(conversation, f"语音已转写，正在转交给 {self._settings.provider}…")
            prompt = self._core._media_handler.build_voice_prompt(transcript)
            self._core.run_prompt(conversation, prompt=prompt, start_text=None)
        except MediaHandlerError as exc:
            self.send_message(conversation, f"WhatsApp 音频处理失败:\n{exc}")

    def _download_media(self, *, media_id: str, caption: str, default_name: str):
        metadata = self._graph_get(f"/{media_id}")
        download_url = str(metadata.get("url") or "").strip()
        if not download_url:
            raise MediaHandlerError(f"WhatsApp media lookup did not return url: {metadata}")
        mime_type = metadata.get("mime_type")
        request = Request(download_url, method="GET")
        request.add_header("Authorization", f"Bearer {self._settings.whatsapp_access_token}")
        local_name = str(metadata.get("id") or default_name)
        if "." not in local_name:
            local_name = default_name
        return self._core._media_handler.download(
            file_url=download_url,
            file_id=media_id,
            file_name=local_name,
            mime_type=mime_type,
            caption=caption,
            headers={"Authorization": f"Bearer {self._settings.whatsapp_access_token}"},
        )

    def _graph_get(self, path: str) -> dict[str, Any]:
        url = f"{self._settings.whatsapp_api_base}{path}"
        request = Request(url, method="GET")
        request.add_header("Authorization", f"Bearer {self._settings.whatsapp_access_token}")
        return self._execute_request(request)

    def _graph_post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._settings.whatsapp_api_base}{path}"
        request = Request(url, data=json.dumps(payload).encode("utf-8"), method="POST")
        request.add_header("Authorization", f"Bearer {self._settings.whatsapp_access_token}")
        request.add_header("Content-Type", "application/json")
        return self._execute_request(request)

    @staticmethod
    def _execute_request(request: Request) -> dict[str, Any]:
        try:
            with urlopen(request, timeout=60) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"WhatsApp HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"WhatsApp request failed: {exc}") from exc
        return json.loads(raw) if raw else {}

    def _validate_config(self) -> None:
        missing: list[str] = []
        if not self._settings.whatsapp_verify_token:
            missing.append("WHATSAPP_VERIFY_TOKEN")
        if not self._settings.whatsapp_access_token:
            missing.append("WHATSAPP_ACCESS_TOKEN")
        if not self._settings.whatsapp_phone_number_id:
            missing.append("WHATSAPP_PHONE_NUMBER_ID")
        if missing:
            raise RuntimeError(f"WhatsApp is enabled but missing config: {', '.join(missing)}")
