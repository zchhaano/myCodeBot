from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from approval_state import ApprovalState, PendingApproval
from bridge_runner import BridgeRunner, RunnerError, RunnerResponse
from channel_keys import ConversationRef
from chat_log import ChatLogStore
from claude_runner import format_text_reply
from codex_usage import load_codex_usage
from config import Settings
from media_handler import MediaHandler
from resume_telegram_session import (
    format_resume_target,
    get_resume_target,
    get_resume_targets_for_chat,
)
from runtime_state import BridgeRuntimeState
from runner_factory import build_runner
from session_store import SessionStore
from version_info import get_version_snapshot
from workdir_store import WorkdirStore


LOGGER = logging.getLogger("telegram-claude-bridge.core")

PERMISSION_PATTERNS = (
    re.compile(r"(需要|请求|请|需要先).{0,12}(授权|权限)"),
    re.compile(r"(写入|编辑|修改).{0,12}(README|文件|权限|授权)"),
    re.compile(r"(permission|approval|authorize)", re.IGNORECASE),
    re.compile(r"(write|edit).{0,20}(access|permission)", re.IGNORECASE),
)

APPROVAL_CONTINUE_PROMPT = (
    "The user approved the pending file-edit permission request. "
    "Continue the previously blocked task now using the newly granted permissions. "
    "Do not ask again for the same edit permission unless broader access is required."
)

AUTO_APPROVAL_REPEAT_LIMIT = 2


@dataclass(frozen=True)
class SentMessage:
    message_id: str | None = None
    raw: dict | None = None


class BridgeTransport(Protocol):
    can_edit_messages: bool

    def send_message(self, conversation: ConversationRef, text: str, role: str = "system") -> SentMessage | None: ...
    def edit_message(
        self,
        conversation: ConversationRef,
        message_id: str,
        text: str,
        role: str = "system",
    ) -> SentMessage | None: ...
    def help_channel_label(self) -> str: ...


class BridgeCore:
    def __init__(
        self,
        settings: Settings,
        store: SessionStore,
        runner: BridgeRunner,
        media_handler: MediaHandler,
        runtime_state: BridgeRuntimeState,
        version_info: dict[str, str],
        approvals: ApprovalState,
        workdirs: WorkdirStore,
        chat_log: ChatLogStore,
        transport: BridgeTransport,
    ) -> None:
        self._settings = settings
        self._store = store
        self._runner = runner
        self._media_handler = media_handler
        self._runtime_state = runtime_state
        self._version_info = version_info
        self._approvals = approvals
        self._workdirs = workdirs
        self._chat_log = chat_log
        self._transport = transport
        self._conversation_locks: dict[str, threading.RLock] = {}
        self._conversation_locks_guard = threading.Lock()

    def process_text(self, conversation: ConversationRef, text: str) -> None:
        with self._lock_for(conversation):
            self._dispatch_text(conversation, text)

    def run_prompt(
        self,
        conversation: ConversationRef,
        *,
        prompt: str,
        start_text: str | None,
        image_paths: list[str] | None = None,
    ) -> None:
        if self._settings.claude_streaming:
            self._dispatch_streaming(
                conversation=conversation,
                text=prompt,
                start_text=start_text,
                image_paths=image_paths,
            )
            return

        if start_text:
            self._send_message(conversation, start_text)
        self._runtime_state.request_started()

        try:
            record = self._store.get(conversation.key)
            runner = self._runner_for_conversation(conversation)
            workdir = str(self._effective_workdir(conversation))
            if record is None:
                response = runner.ask_new(prompt, image_paths=image_paths)
            else:
                response = runner.ask_resume(record.session_id, prompt, image_paths=image_paths)

            self._store.set(conversation.key, session_id=response.session_id, cwd=workdir)
            for part in format_text_reply(response.text):
                self._send_message(conversation, part, role="assistant")
            self._capture_permission_request(
                conversation=conversation,
                original_prompt=prompt,
                session_id=response.session_id,
                assistant_text=response.text,
            )
            self._runtime_state.request_succeeded()
        except RunnerError as exc:
            LOGGER.exception("Provider invocation failed for conversation %s", conversation.key)
            self._runtime_state.request_failed(str(exc))
            for part in format_text_reply(f"{self._provider_label()} 调用失败:\n{exc}"):
                self._send_message(conversation, part)

    def build_status_text(self, conversation: ConversationRef) -> str:
        record = self._store.get(conversation.key)
        effective_workdir = self._effective_workdir(conversation)
        project_override = self._workdirs.get(conversation.key)
        base_lines = [
            "当前没有绑定会话。" if record is None else "当前会话状态:",
            f"bot: {self._settings.name}",
            f"provider: {self._provider_label()}",
            f"channel: {conversation.channel}",
            f"chat_id: {conversation.chat_id}",
            f"workdir: {effective_workdir}" if record is None else f"cwd: {record.cwd}",
            f"streaming: {self._settings.claude_streaming}",
            f"project_override: {project_override or 'off'}",
            f"pending_approval: {'yes' if self._approvals.get(conversation.key) else 'no'}",
            f"approve_always: {self._approvals.get_always_mode(conversation.key) or 'off'}",
        ]
        if record is not None:
            base_lines.insert(1, f"session_id: {record.session_id}")
            base_lines.insert(3, f"updated_at: {record.updated_at}")

        if self._settings.provider == "codex" and record is not None:
            usage = load_codex_usage(record.session_id)
            if usage is None:
                base_lines.append("codex_usage: unavailable")
            else:
                base_lines.extend(
                    [
                        f"codex_total_tokens: {usage.total_tokens}",
                        f"codex_input_tokens: {usage.input_tokens}",
                        f"codex_cached_input_tokens: {usage.cached_input_tokens}",
                        f"codex_output_tokens: {usage.output_tokens}",
                        f"codex_reasoning_output_tokens: {usage.reasoning_output_tokens}",
                        f"codex_plan: {usage.plan_type or 'unknown'}",
                        f"codex_primary_used_percent: {usage.primary_used_percent if usage.primary_used_percent is not None else 'unknown'}",
                        f"codex_secondary_used_percent: {usage.secondary_used_percent if usage.secondary_used_percent is not None else 'unknown'}",
                    ]
                )

        return "\n".join(base_lines)

    def build_health_text(self) -> str:
        snapshot = self._runtime_state.snapshot()
        return (
            "Bridge health:\n"
            f"started_at: {snapshot.started_at}\n"
            f"messages_total: {snapshot.messages_total}\n"
            f"requests_total: {snapshot.requests_total}\n"
            f"active_requests: {snapshot.active_requests}\n"
            f"last_success_at: {snapshot.last_success_at or 'none'}\n"
            f"last_error_at: {snapshot.last_error_at or 'none'}\n"
            f"last_error: {snapshot.last_error or 'none'}\n"
            f"session_count: {len(self._store.items())}\n"
            f"pending_approvals: {self._approvals.count()}\n"
            f"approve_always_chats: {self._approvals.always_count()}\n"
            f"provider: {self._provider_label()}\n"
            f"streaming: {self._settings.claude_streaming}\n"
            f"status_web: {'on' if self._settings.status_web_enabled else 'off'}"
        )

    def build_version_text(self) -> str:
        return (
            "Bridge version:\n"
            f"provider: {self._version_info['provider']}\n"
            f"git_commit: {self._version_info['git_commit']}\n"
            f"claude_version: {self._version_info['claude_version']}\n"
            f"codex_version: {self._version_info['codex_version']}\n"
            f"copilot_version: {self._version_info['copilot_version']}\n"
            f"whisper_bin: {self._version_info['whisper_bin']}\n"
            f"whisper_resolved: {self._version_info['whisper_resolved']}\n"
            f"python: {self._version_info['python']}\n"
            f"platform: {self._version_info['platform']}\n"
            f"claude_bin: {self._version_info['claude_bin']}\n"
            f"codex_bin: {self._version_info['codex_bin']}\n"
            f"copilot_bin: {self._version_info['copilot_bin']}"
        )

    def build_project_status_text(self, conversation: ConversationRef) -> str:
        project_override = self._workdirs.get(conversation.key)
        allowed_roots = [str(path) for path in self._allowed_project_roots()]
        return "\n".join(
            [
                "当前项目目录状态:",
                f"bot: {self._settings.name}",
                f"provider: {self._provider_label()}",
                f"channel: {conversation.channel}",
                f"chat_id: {conversation.chat_id}",
                f"default_workdir: {self._settings.claude_workdir}",
                f"allowed_roots: {', '.join(allowed_roots)}",
                f"chat_workdir: {project_override or 'not set'}",
                f"effective_workdir: {self._effective_workdir(conversation)}",
            ]
        )

    def submit_web_prompt(
        self,
        conversation: ConversationRef,
        prompt: str,
        *,
        mirror_to_channel: bool = True,
    ) -> None:
        worker = threading.Thread(
            target=self._run_web_prompt,
            args=(conversation, prompt, mirror_to_channel),
            name=f"web-chat-{conversation.key}",
            daemon=True,
        )
        worker.start()

    def log_message(self, conversation: ConversationRef, *, role: str, source: str, text: str) -> None:
        clean = text.strip()
        if not clean:
            return
        self._chat_log.append(
            chat_id=conversation.key,
            channel=conversation.channel,
            role=role,
            source=source,
            text=clean,
        )

    def _dispatch_text(self, conversation: ConversationRef, text: str) -> None:
        if text.startswith("/start"):
            self._send_message(conversation, self._help_text())
            return
        if text.startswith("/help"):
            self._send_message(conversation, self._help_text())
            return
        if text.startswith("/status"):
            self._send_message(conversation, self.build_status_text(conversation))
            return
        if text.startswith("/health"):
            self._send_message(conversation, self.build_health_text())
            return
        if text.startswith("/version"):
            self._send_message(conversation, self.build_version_text())
            return
        if text.startswith("/clear"):
            self._send_message(
                conversation,
                "已清除当前会话。" if self._store.clear(conversation.key) else "当前没有可清除的会话。",
            )
            self._approvals.clear(conversation.key)
            return
        if text.startswith("/project_status"):
            self._send_message(conversation, self.build_project_status_text(conversation))
            return
        if text.startswith("/project"):
            self._dispatch_project_command(conversation, text)
            return
        if text.startswith("/resume_local"):
            self._dispatch_resume_local(conversation, text)
            return
        if text.startswith("/approve_bypass") or text.startswith("/approve-bypass"):
            self._dispatch_set_always_mode(conversation, permission_mode="bypassPermissions", label="bypassPermissions")
            return
        if text.startswith("/approve_always") or text.startswith("/approve-always"):
            self._dispatch_approve_always(conversation)
            return
        if text.startswith("/approve_manual") or text.startswith("/approve-manual"):
            cleared = self._approvals.clear_always_mode(conversation.key)
            self._send_message(
                conversation,
                "已关闭自动批准，后续权限请求将再次等待 /approve。"
                if cleared
                else "当前没有开启自动批准。",
            )
            return
        if text.startswith("/approve"):
            self._dispatch_approval(conversation)
            return
        if text.startswith("/deny"):
            cleared = self._approvals.clear(conversation.key)
            self._send_message(
                conversation,
                "已拒绝本次待授权操作。" if cleared else "当前没有待授权操作。",
            )
            return

        self.log_message(conversation, role="user", source=conversation.channel, text=text)
        self.run_prompt(
            conversation,
            prompt=text,
            start_text=f"请求已收到，正在调用本机 {self._provider_label()}…",
        )

    def _dispatch_streaming(
        self,
        *,
        conversation: ConversationRef,
        text: str,
        start_text: str | None,
        image_paths: list[str] | None = None,
    ) -> None:
        sent = self._send_message(
            conversation,
            start_text or f"请求已收到，正在流式调用本机 {self._provider_label()}…",
        )
        message_id = sent.message_id if sent else None
        record = self._store.get(conversation.key)
        latest_text = ""
        final_session_id = record.session_id if record else None
        last_preview = None
        last_edit_at = 0.0
        self._runtime_state.request_started()

        try:
            runner = self._runner_for_conversation(conversation)
            workdir = str(self._effective_workdir(conversation))
            if record is None:
                stream = runner.stream_new(text, image_paths=image_paths)
            else:
                stream = runner.stream_resume(record.session_id, text, image_paths=image_paths)

            for update in stream:
                if update.get("session_id"):
                    final_session_id = update["session_id"]
                if update.get("text"):
                    latest_text = update["text"]

                preview = self._make_live_preview(latest_text)
                now = time.monotonic()
                if (
                    self._transport.can_edit_messages
                    and preview
                    and preview != last_preview
                    and message_id is not None
                    and now - last_edit_at >= self._settings.telegram_edit_interval_seconds
                ):
                    self._edit_message(conversation, message_id, preview)
                    last_preview = preview
                    last_edit_at = now

            if final_session_id:
                self._store.set(conversation.key, session_id=final_session_id, cwd=workdir)

            parts = format_text_reply(latest_text)
            for part in parts:
                self.log_message(conversation, role="assistant", source="bridge", text=part)
            if message_id is None or not self._transport.can_edit_messages:
                for part in parts:
                    self._send_message(conversation, part, role="assistant")
            else:
                if parts and parts[0] != last_preview:
                    self._edit_message(conversation, message_id, parts[0], role="assistant")
                for part in parts[1:]:
                    self._send_message(conversation, part, role="assistant")
            self._capture_permission_request(
                conversation=conversation,
                original_prompt=text,
                session_id=final_session_id,
                assistant_text=latest_text,
            )
            self._runtime_state.request_succeeded()
        except RunnerError as exc:
            LOGGER.exception("Provider streaming invocation failed for conversation %s", conversation.key)
            self._runtime_state.request_failed(str(exc))
            error_text = f"{self._provider_label()} 调用失败:\n{exc}"
            if message_id is not None and self._transport.can_edit_messages:
                parts = format_text_reply(error_text)
                if parts:
                    self._edit_message(conversation, message_id, parts[0])
                for part in parts[1:]:
                    self._send_message(conversation, part)
            else:
                for part in format_text_reply(error_text):
                    self._send_message(conversation, part)

    def _capture_permission_request(
        self,
        *,
        conversation: ConversationRef,
        original_prompt: str,
        session_id: str | None,
        assistant_text: str,
    ) -> None:
        if not self._looks_like_permission_request(assistant_text):
            self._approvals.clear(conversation.key)
            self._approvals.reset_auto_request(conversation.key)
            return

        always_mode = self._approvals.get_always_mode(conversation.key)
        permission_mode = always_mode or self._settings.claude_approval_permission_mode
        approval = self._approvals.set(
            chat_id=conversation.key,
            channel=conversation.channel,
            session_id=session_id,
            cwd=str(self._effective_workdir(conversation)),
            original_prompt=original_prompt,
            permission_mode=permission_mode,
            assistant_message=assistant_text,
        )
        if always_mode:
            fingerprint = f"{approval.permission_mode}\n{approval.assistant_message.strip()}"
            repeat_count = self._approvals.record_auto_request(conversation.key, fingerprint)
            if repeat_count >= AUTO_APPROVAL_REPEAT_LIMIT:
                self._send_message(
                    conversation,
                    "检测到相同权限请求被重复触发，已停止自动重试，避免死循环。\n"
                    f"当前自动批准模式: {approval.permission_mode}\n"
                    "这通常表示当前模式不够覆盖所需权限。"
                    "\n如果是 git add / git commit 之类的 Bash 权限，请改用 /approve_bypass；"
                    "\n如果你不想放开更高权限，发送 /approve_manual 恢复手动确认。",
                )
                return
            self._send_message(
                conversation,
                f"检测到权限请求，已按自动批准继续。\nmode: {approval.permission_mode}",
            )
            self._dispatch_approval(conversation, auto_approved=True)
            return

        self._send_message(
            conversation,
            f"检测到 {self._provider_label()} 在请求文件/工具权限。\n"
            f"mode: {approval.permission_mode}\n"
            "发送 /approve 继续这次操作，发送 /deny 取消。\n"
            "如果想当前 chat 后续自动批准编辑权限，发送 /approve_always。\n"
            "如果你连 Bash/git 权限也想自动放行，发送 /approve_bypass。",
        )

    def _dispatch_approve_always(self, conversation: ConversationRef) -> None:
        self._dispatch_set_always_mode(
            conversation,
            permission_mode=self._settings.claude_approval_permission_mode,
            label=self._settings.claude_approval_permission_mode,
        )

    def _dispatch_set_always_mode(self, conversation: ConversationRef, *, permission_mode: str, label: str) -> None:
        self._approvals.set_always_mode(conversation.key, permission_mode)
        self._send_message(
            conversation,
            "已开启当前 chat 的自动批准。\n"
            f"mode: {label}\n"
            "后续检测到编辑/写入权限请求时会自动继续。关闭请发送 /approve_manual。",
        )
        if self._approvals.get(conversation.key):
            self._dispatch_approval(conversation, auto_approved=True)

    def _dispatch_approval(self, conversation: ConversationRef, *, auto_approved: bool = False) -> None:
        approval = self._approvals.pop(conversation.key)
        if approval is None:
            self._send_message(conversation, "当前没有待授权操作。")
            return
        if auto_approved:
            self._send_message(conversation, f"正在以 {approval.permission_mode} 自动继续执行…")
        else:
            self._send_message(conversation, f"已批准本次操作，正在以 {approval.permission_mode} 继续执行…")
        self._runtime_state.request_started()

        try:
            response = self._continue_after_approval(approval)
            if response.session_id:
                self._store.set(conversation.key, session_id=response.session_id, cwd=approval.cwd)
            for part in format_text_reply(response.text):
                self._send_message(conversation, part, role="assistant")
            self._capture_permission_request(
                conversation=conversation,
                original_prompt=approval.original_prompt,
                session_id=response.session_id,
                assistant_text=response.text,
            )
            self._runtime_state.request_succeeded()
        except RunnerError as exc:
            LOGGER.exception("Approval continuation failed for conversation %s", conversation.key)
            self._runtime_state.request_failed(str(exc))
            for part in format_text_reply(f"{self._provider_label()} 授权续跑失败:\n{exc}"):
                self._send_message(conversation, part)

    def _continue_after_approval(self, approval: PendingApproval) -> RunnerResponse:
        runner = self._runner_for_workdir(Path(approval.cwd))
        if self._settings.claude_streaming:
            if approval.session_id:
                updates = runner.stream_resume(
                    approval.session_id,
                    APPROVAL_CONTINUE_PROMPT,
                    permission_mode_override=approval.permission_mode,
                )
            else:
                updates = runner.stream_new(
                    approval.original_prompt,
                    permission_mode_override=approval.permission_mode,
                )

            latest_text = ""
            final_session_id = approval.session_id
            for update in updates:
                if update.get("session_id"):
                    final_session_id = update["session_id"]
                if update.get("text"):
                    latest_text = update["text"]
            return RunnerResponse(
                session_id=final_session_id or "",
                text=latest_text,
                raw={"type": "approval_stream_result"},
                command=[],
            )

        if approval.session_id:
            return runner.ask_resume(
                approval.session_id,
                APPROVAL_CONTINUE_PROMPT,
                permission_mode_override=approval.permission_mode,
            )
        return runner.ask_new(
            approval.original_prompt,
            permission_mode_override=approval.permission_mode,
        )

    def _dispatch_project_command(self, conversation: ConversationRef, text: str) -> None:
        parts = text.split(maxsplit=1)
        if len(parts) == 1 or not parts[1].strip():
            self._send_message(conversation, "用法:\n/project ~/projects/my-new-app\n/project default")
            return

        raw_target = parts[1].strip()
        if raw_target.lower() in {"default", "reset"}:
            cleared = self._workdirs.clear(conversation.key)
            self._store.clear(conversation.key)
            self._approvals.clear(conversation.key)
            self._send_message(
                conversation,
                "已恢复默认项目目录并清除当前会话。"
                if cleared
                else "当前已在默认项目目录，已清除当前会话。",
            )
            return

        candidate = Path(raw_target).expanduser()
        if not candidate.is_absolute():
            candidate = (self._effective_workdir(conversation) / candidate).resolve()
        else:
            candidate = candidate.resolve()

        matched_root = self._find_allowed_project_root(candidate)
        if matched_root is None:
            allowed_roots = "\n".join(f"- {path}" for path in self._allowed_project_roots())
            self._send_message(
                conversation,
                "项目目录必须位于允许的工作区范围内。\n"
                f"allowed_roots:\n{allowed_roots}\n"
                f"requested: {candidate}",
            )
            return

        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._send_message(conversation, f"创建项目目录失败:\n{exc}")
            return
        if not candidate.is_dir():
            self._send_message(conversation, f"目标不是目录:\n{candidate}")
            return

        self._workdirs.set(conversation.key, str(candidate))
        self._store.clear(conversation.key)
        self._approvals.clear(conversation.key)
        self._send_message(
            conversation,
            "已切换当前 chat 的项目目录，并清除旧会话。\n"
            f"allowed_root: {matched_root}\n"
            f"workdir: {candidate}\n"
            "现在可以直接让机器人在这个目录里开始新项目。",
        )

    def _dispatch_resume_local(self, conversation: ConversationRef, text: str) -> None:
        parts = text.split(maxsplit=1)
        provider = parts[1].strip().lower() if len(parts) > 1 and parts[1].strip() else None
        if provider and provider not in {"claude", "codex", "copilot"}:
            self._send_message(conversation, "用法:\n/resume_local\n/resume_local claude\n/resume_local codex")
            return
        try:
            if provider:
                targets = [get_resume_target(chat_id=conversation.key, provider=provider)]
            else:
                targets = get_resume_targets_for_chat(conversation.key)
        except RuntimeError as exc:
            self._send_message(conversation, f"生成本地续聊命令失败:\n{exc}")
            return
        if not targets:
            self._send_message(conversation, "当前 chat 没有可恢复的本地会话。")
            return
        header = f"本地继续这个 {self._transport.help_channel_label()} 会话可用以下命令："
        body = "\n\n".join(format_resume_target(target) for target in targets)
        for part in format_text_reply(f"{header}\n\n{body}"):
            self._send_message(conversation, part)

    def _run_web_prompt(self, conversation: ConversationRef, prompt: str, mirror_to_channel: bool) -> None:
        clean = prompt.strip()
        if not clean:
            return
        with self._lock_for(conversation):
            self._runtime_state.record_message()
            self.log_message(conversation, role="user", source="web", text=clean)
            if mirror_to_channel:
                self._transport.send_message(conversation, f"[Desktop] {clean}", role="system")
            self.run_prompt(conversation, prompt=clean, start_text=None)

    def _effective_workdir(self, conversation: ConversationRef) -> Path:
        override = self._workdirs.get(conversation.key)
        if override:
            return Path(override)
        return self._settings.claude_workdir

    def _runner_for_conversation(self, conversation: ConversationRef) -> BridgeRunner:
        return self._runner_for_workdir(self._effective_workdir(conversation))

    def _runner_for_workdir(self, workdir: Path) -> BridgeRunner:
        return build_runner(replace(self._settings, claude_workdir=workdir))

    def _help_text(self) -> str:
        return (
            f"bot: {self._settings.name}\n"
            f"{self._transport.help_channel_label()} 已连接到本机 {self._provider_label()} 后端。\n"
            f"直接发文本即可转发到 {self._provider_label()}。\n"
            "也支持图片和语音消息。\n"
            "命令: /help /status /health /version /clear /project /project_status /approve /deny "
            "/approve_always /approve_bypass /approve_manual /resume_local"
        )

    def _allowed_project_roots(self) -> list[Path]:
        roots = [self._settings.claude_workdir.resolve()]
        for path in self._settings.claude_allowed_workdirs:
            resolved = path.resolve()
            if resolved not in roots:
                roots.append(resolved)
        return roots

    def _find_allowed_project_root(self, candidate: Path) -> Path | None:
        for root in self._allowed_project_roots():
            try:
                candidate.relative_to(root)
                return root
            except ValueError:
                continue
        return None

    def _send_message(self, conversation: ConversationRef, text: str, role: str = "system") -> SentMessage:
        self.log_message(conversation, role=role, source="bridge", text=text)
        return self._transport.send_message(conversation, text, role=role) or SentMessage()

    def _edit_message(self, conversation: ConversationRef, message_id: str, text: str, role: str = "system") -> SentMessage:
        result = self._transport.edit_message(conversation, message_id, text, role=role)
        return result or SentMessage(message_id=message_id)

    def _lock_for(self, conversation: ConversationRef) -> threading.RLock:
        with self._conversation_locks_guard:
            lock = self._conversation_locks.get(conversation.key)
            if lock is None:
                lock = threading.RLock()
                self._conversation_locks[conversation.key] = lock
            return lock

    def _provider_label(self) -> str:
        return self._settings.provider

    @staticmethod
    def _make_live_preview(text: str, limit: int = 3900) -> str:
        clean = text.strip()
        if not clean:
            return ""
        if len(clean) <= limit:
            return clean
        prefix = "[streaming，显示最近内容]\n\n"
        keep = max(256, limit - len(prefix))
        return prefix + clean[-keep:]

    @staticmethod
    def _looks_like_permission_request(text: str) -> bool:
        clean = text.strip()
        if not clean:
            return False
        return any(pattern.search(clean) for pattern in PERMISSION_PATTERNS)
