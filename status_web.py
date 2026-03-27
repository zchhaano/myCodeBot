from __future__ import annotations

import html
import json
import logging
import shlex
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from chat_log import ChatLogStore
from config import Settings
from codex_usage import load_codex_usage
from resume_telegram_session import get_resume_targets_for_chat
from runtime_state import BridgeRuntimeState
from session_store import SessionStore
from workdir_store import WorkdirStore


LOGGER = logging.getLogger("telegram-claude-bridge.status-web")


def start_status_server(
    settings: Settings,
    store: SessionStore,
    workdirs: WorkdirStore,
    approvals,
    runtime_state: BridgeRuntimeState,
    version_info: dict[str, str],
    chat_log: ChatLogStore,
    submit_prompt,
) -> ThreadingHTTPServer:
    handler_class = _build_handler(
        settings,
        store,
        workdirs,
        approvals,
        runtime_state,
        version_info,
        chat_log,
        submit_prompt,
    )
    server = ThreadingHTTPServer((settings.status_web_host, settings.status_web_port), handler_class)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    LOGGER.info(
        "Started status web on http://%s:%s",
        settings.status_web_host,
        settings.status_web_port,
    )
    return server


def _build_handler(
    settings: Settings,
    store: SessionStore,
    workdirs: WorkdirStore,
    approvals,
    runtime_state: BridgeRuntimeState,
    version_info: dict[str, str],
    chat_log: ChatLogStore,
    submit_prompt,
):
    class StatusHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if not _is_authorized(settings, self.headers.get("Authorization"), parsed.query):
                self._send_unauthorized()
                return

            if parsed.path == "/api/status":
                self._send_json(
                    _status_payload(settings, store, workdirs, approvals, runtime_state, version_info, chat_log)
                )
                return
            if parsed.path == "/api/chats":
                self._send_json(_chat_list_payload(store, workdirs, approvals, chat_log))
                return
            if parsed.path == "/api/chat":
                chat_id = _parse_chat_id(parse_qs(parsed.query).get("chat_id", [None])[0])
                if chat_id is None:
                    self.send_error(400, "Missing or invalid chat_id")
                    return
                self._send_json(_chat_payload(chat_id, store, workdirs, approvals, chat_log))
                return
            if parsed.path == "/":
                self._send_html(
                    _render_status_html(
                        _status_payload(settings, store, workdirs, approvals, runtime_state, version_info, chat_log)
                    )
                )
                return
            if parsed.path == "/chat":
                self._send_html(_render_chat_html(settings))
                return
            self.send_error(404, "Not Found")

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if not _is_authorized(settings, self.headers.get("Authorization"), parsed.query):
                self._send_unauthorized()
                return
            if parsed.path != "/api/chat/send":
                self.send_error(404, "Not Found")
                return

            payload = self._read_json_body()
            chat_id = _parse_chat_id(payload.get("chat_id"))
            prompt = str(payload.get("prompt") or "").strip()
            mirror_to_telegram = bool(payload.get("mirror_to_telegram", True))
            if chat_id is None or not prompt:
                self.send_error(400, "chat_id and prompt are required")
                return

            submit_prompt(chat_id, prompt, mirror_to_telegram=mirror_to_telegram)
            self._send_json({"ok": True, "chat_id": chat_id, "queued": True})

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            LOGGER.info("%s - %s", self.address_string(), format % args)

        def _send_json(self, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_html(self, body: str) -> None:
            encoded = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_unauthorized(self) -> None:
            encoded = b"Unauthorized"
            self.send_response(401)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("WWW-Authenticate", 'Bearer realm="telegram-claude-bridge-status"')
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length > 0 else b"{}"
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))

    return StatusHandler


def _is_authorized(settings: Settings, authorization_header: str | None, query: str) -> bool:
    expected = settings.status_web_token
    if not expected:
        return True

    if authorization_header:
        scheme, _, token = authorization_header.partition(" ")
        if scheme.lower() == "bearer" and token == expected:
            return True

    params = parse_qs(query, keep_blank_values=False)
    query_tokens = params.get("token") or []
    return expected in query_tokens


def _status_payload(
    settings: Settings,
    store: SessionStore,
    workdirs: WorkdirStore,
    approvals,
    runtime_state: BridgeRuntimeState,
    version_info: dict[str, str],
    chat_log: ChatLogStore,
) -> dict[str, Any]:
    snapshot = runtime_state.snapshot()
    sessions = []
    for chat_id, record in store.items():
        usage = load_codex_usage(record.session_id) if settings.provider == "codex" else None
        sessions.append(
            {
                "chat_id": chat_id,
                "session_id": record.session_id,
                "cwd": record.cwd,
                "updated_at": record.updated_at,
                "codex_usage": usage.to_dict() if usage is not None else None,
            }
        )
    return {
        "service": {
            "name": settings.name,
            "started_at": snapshot.started_at,
            "last_success_at": snapshot.last_success_at,
            "last_error_at": snapshot.last_error_at,
            "last_error": snapshot.last_error,
            "messages_total": snapshot.messages_total,
            "requests_total": snapshot.requests_total,
            "active_requests": snapshot.active_requests,
        },
        "bridge": {
            "provider": settings.provider,
            "workdir": str(settings.claude_workdir),
            "streaming": settings.claude_streaming,
            "approval_store_path": str(settings.approval_store_path),
            "workdir_store_path": str(settings.workdir_store_path),
            "approve_always_chats": approvals.always_count(),
            "project_override_chats": len(workdirs.items()),
            "status_web": {
                "enabled": settings.status_web_enabled,
                "host": settings.status_web_host,
                "port": settings.status_web_port,
            },
        },
        "version": version_info,
        "workdir_overrides": [{"chat_id": chat_id, "cwd": cwd} for chat_id, cwd in workdirs.items()],
        "sessions": sessions,
        "session_count": len(sessions),
        "chat_count": len(_known_chat_ids(store, workdirs, chat_log)),
    }


def _known_chat_ids(store: SessionStore, workdirs: WorkdirStore, chat_log: ChatLogStore) -> list[int]:
    chat_ids = {int(chat_id) for chat_id, _ in store.items()}
    chat_ids.update(int(chat_id) for chat_id, _ in workdirs.items())
    chat_ids.update(chat_log.chat_ids())
    return sorted(chat_ids)


def _chat_list_payload(
    store: SessionStore,
    workdirs: WorkdirStore,
    approvals,
    chat_log: ChatLogStore,
) -> dict[str, Any]:
    chats = []
    for chat_id in _known_chat_ids(store, workdirs, chat_log):
        record = store.get(chat_id)
        chats.append(
            {
                "chat_id": chat_id,
                "session_id": record.session_id if record else None,
                "updated_at": record.updated_at if record else None,
                "cwd": record.cwd if record else workdirs.get(chat_id),
                "pending_approval": approvals.get(chat_id) is not None,
                "message_count": len(chat_log.items(chat_id, limit=0)),
            }
        )
    return {"chats": chats}


def _chat_payload(
    chat_id: int,
    store: SessionStore,
    workdirs: WorkdirStore,
    approvals,
    chat_log: ChatLogStore,
) -> dict[str, Any]:
    record = store.get(chat_id)
    resume_targets = get_resume_targets_for_chat(chat_id)
    messages = [
        {
            "id": item.id,
            "role": item.role,
            "source": item.source,
            "text": item.text,
            "created_at": item.created_at,
        }
        for item in chat_log.items(chat_id)
    ]
    return {
        "chat_id": chat_id,
        "session_id": record.session_id if record else None,
        "updated_at": record.updated_at if record else None,
        "cwd": record.cwd if record else workdirs.get(chat_id),
        "pending_approval": approvals.get(chat_id) is not None,
        "resume_targets": [
            {
                "bot": target.settings.name,
                "provider": target.settings.provider,
                "session_id": target.record.session_id,
                "cwd": target.record.cwd,
                "command": shlex.join(target.command),
            }
            for target in resume_targets
        ],
        "messages": messages,
    }


def _parse_chat_id(raw: Any) -> int | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or not text.lstrip("-").isdigit():
        return None
    return int(text)


def _render_status_html(payload: dict[str, Any]) -> str:
    service = payload["service"]
    bridge = payload["bridge"]
    version = payload["version"]
    sessions = payload["sessions"]

    rows = "\n".join(
        (
            "<tr>"
            f"<td>{html.escape(str(item['chat_id']))}</td>"
            f"<td>{html.escape(item['session_id'])}</td>"
            f"<td>{html.escape(item['updated_at'])}</td>"
            f"<td>{html.escape(item['cwd'])}</td>"
            "</tr>"
        )
        for item in sessions
    ) or '<tr><td colspan="4">No sessions</td></tr>'

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Telegram Agent Bridge</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f4f1ea;
      --panel: #fffdf8;
      --ink: #182028;
      --muted: #5d6773;
      --line: #d9d1c2;
      --accent: #0e7490;
    }}
    body {{
      margin: 0;
      font-family: "Iowan Old Style", "Palatino Linotype", serif;
      background: radial-gradient(circle at top left, #fff7df, var(--bg) 45%);
      color: var(--ink);
    }}
    main {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 32px 20px 48px;
    }}
    h1, h2 {{
      margin: 0 0 12px;
      font-weight: 700;
      letter-spacing: 0.01em;
    }}
    p {{ color: var(--muted); }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin: 24px 0;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 18px;
      box-shadow: 0 10px 30px rgba(24, 32, 40, 0.05);
    }}
    .label {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 8px;
    }}
    .value {{
      font-size: 24px;
      font-weight: 700;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 16px;
      overflow: hidden;
    }}
    th, td {{
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      font-size: 14px;
    }}
    th {{
      background: #f8f2e7;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
    }}
    code {{
      color: var(--accent);
      font-family: "SFMono-Regular", Consolas, monospace;
    }}
    .meta {{
      display: grid;
      gap: 8px;
      margin-top: 12px;
    }}
    a {{ color: var(--accent); }}
  </style>
</head>
<body>
  <main>
    <h1>Telegram Agent Bridge</h1>
    <p>Local-only status page. JSON endpoint: <code>/api/status</code>. Chat UI: <a href="/chat">/chat</a></p>
    <div class="grid">
      <section class="card"><div class="label">Requests</div><div class="value">{service['requests_total']}</div></section>
      <section class="card"><div class="label">Messages</div><div class="value">{service['messages_total']}</div></section>
      <section class="card"><div class="label">Active Requests</div><div class="value">{service['active_requests']}</div></section>
      <section class="card"><div class="label">Session Count</div><div class="value">{payload['session_count']}</div></section>
      <section class="card"><div class="label">Chat Count</div><div class="value">{payload['chat_count']}</div></section>
    </div>
    <div class="grid">
      <section class="card">
        <h2>Service</h2>
        <div class="meta">
          <div>Started: <code>{html.escape(str(service['started_at']))}</code></div>
          <div>Last success: <code>{html.escape(str(service['last_success_at']))}</code></div>
          <div>Last error: <code>{html.escape(str(service['last_error'] or 'none'))}</code></div>
        </div>
      </section>
      <section class="card">
        <h2>Version</h2>
        <div class="meta">
          <div>Git: <code>{html.escape(version['git_commit'])}</code></div>
          <div>Provider: <code>{html.escape(version['provider'])}</code></div>
          <div>Claude: <code>{html.escape(version['claude_version'])}</code></div>
          <div>Codex: <code>{html.escape(version['codex_version'])}</code></div>
          <div>Copilot: <code>{html.escape(version['copilot_version'])}</code></div>
          <div>Python: <code>{html.escape(version['python'])}</code></div>
          <div>Platform: <code>{html.escape(version['platform'])}</code></div>
        </div>
      </section>
      <section class="card">
        <h2>Bridge</h2>
        <div class="meta">
          <div>Provider: <code>{html.escape(bridge['provider'])}</code></div>
          <div>Workdir: <code>{html.escape(bridge['workdir'])}</code></div>
          <div>Streaming: <code>{html.escape(str(bridge['streaming']))}</code></div>
          <div>Status web: <code>{html.escape(str(bridge['status_web']['host']))}:{bridge['status_web']['port']}</code></div>
        </div>
      </section>
    </div>
    <section>
      <h2>Sessions</h2>
      <table>
        <thead>
          <tr><th>Chat ID</th><th>Session ID</th><th>Updated</th><th>CWD</th></tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </section>
  </main>
</body>
</html>"""


def _render_chat_html(settings: Settings) -> str:
    title = html.escape(settings.name)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Local Chat - {title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f3efe7;
      --panel: #fffdfa;
      --ink: #1d252d;
      --muted: #64707c;
      --line: #d7cfbf;
      --accent: #0f766e;
      --user: #ddf4ff;
      --assistant: #f6f0d8;
      --system: #f2f2f2;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Iowan Old Style", "Palatino Linotype", serif;
      background:
        radial-gradient(circle at top left, #fff7de 0, rgba(255, 247, 222, 0.7) 28%, transparent 52%),
        linear-gradient(180deg, #f7f2e9, var(--bg));
      color: var(--ink);
    }}
    .layout {{
      display: grid;
      grid-template-columns: 320px minmax(0, 1fr);
      min-height: 100vh;
    }}
    aside {{
      border-right: 1px solid var(--line);
      padding: 20px;
      background: rgba(255, 253, 248, 0.9);
      backdrop-filter: blur(6px);
    }}
    main {{
      display: grid;
      grid-template-rows: auto 1fr auto;
      min-height: 100vh;
    }}
    h1, h2 {{ margin: 0; }}
    .subtle {{ color: var(--muted); }}
    .chat-list {{
      display: grid;
      gap: 10px;
      margin-top: 18px;
    }}
    .chat-item {{
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 14px;
      padding: 12px;
      cursor: pointer;
      text-align: left;
    }}
    .chat-item.active {{
      border-color: var(--accent);
      box-shadow: 0 10px 24px rgba(15, 118, 110, 0.12);
    }}
    .topbar {{
      padding: 20px 24px 12px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 253, 248, 0.8);
    }}
    .resume-strip {{
      margin-top: 14px;
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .resume-card {{
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 10px 12px;
      background: var(--panel);
      min-width: 220px;
    }}
    .resume-card button {{
      margin-top: 8px;
      padding: 8px 12px;
      font-size: 14px;
    }}
    .messages {{
      padding: 22px 24px 28px;
      overflow: auto;
      display: grid;
      gap: 14px;
    }}
    .bubble {{
      max-width: min(820px, 90%);
      border-radius: 18px;
      padding: 14px 16px;
      border: 1px solid var(--line);
      white-space: pre-wrap;
      line-height: 1.45;
      box-shadow: 0 12px 28px rgba(29, 37, 45, 0.04);
    }}
    .bubble.user {{
      justify-self: end;
      background: var(--user);
    }}
    .bubble.assistant {{
      justify-self: start;
      background: var(--assistant);
    }}
    .bubble.system {{
      justify-self: center;
      background: var(--system);
      max-width: 760px;
    }}
    .meta {{
      margin-bottom: 6px;
      font: 12px/1.3 "SFMono-Regular", Consolas, monospace;
      color: var(--muted);
    }}
    form {{
      border-top: 1px solid var(--line);
      background: rgba(255, 253, 248, 0.92);
      padding: 16px 24px 22px;
    }}
    textarea, input {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px 14px;
      font: inherit;
      background: white;
      color: inherit;
    }}
    textarea {{
      min-height: 110px;
      resize: vertical;
      margin-top: 10px;
    }}
    .row {{
      display: grid;
      gap: 12px;
      grid-template-columns: 1fr auto;
      align-items: center;
    }}
    .controls {{
      display: flex;
      gap: 12px;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
    }}
    button {{
      border: 0;
      border-radius: 999px;
      background: var(--accent);
      color: white;
      padding: 12px 18px;
      font: inherit;
      cursor: pointer;
    }}
    label {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: 14px;
    }}
    @media (max-width: 900px) {{
      .layout {{ grid-template-columns: 1fr; }}
      aside {{ border-right: 0; border-bottom: 1px solid var(--line); }}
    }}
  </style>
</head>
<body>
  <div class="layout">
    <aside>
      <h1>Local Chat</h1>
      <p class="subtle">Bridge: {title}</p>
      <input id="chatIdInput" placeholder="Telegram chat_id">
      <div class="chat-list" id="chatList"></div>
    </aside>
    <main>
      <section class="topbar">
        <h2 id="chatTitle">No chat selected</h2>
        <p class="subtle" id="chatMeta">Pick an existing chat or enter a chat_id manually.</p>
        <div class="resume-strip" id="resumeStrip"></div>
      </section>
      <section class="messages" id="messages"></section>
      <form id="composer">
        <div class="controls">
          <label><input type="checkbox" id="mirrorToggle" checked> mirror desktop message to Telegram</label>
          <button type="submit">Send</button>
        </div>
        <textarea id="promptInput" placeholder="Type a message for the shared chat..."></textarea>
      </form>
    </main>
  </div>
  <script>
    const state = {{
      currentChatId: null,
      lastMessageKey: "",
    }};
    const querySuffix = window.location.search || "";

    const chatListEl = document.getElementById("chatList");
    const chatIdInputEl = document.getElementById("chatIdInput");
    const chatTitleEl = document.getElementById("chatTitle");
    const chatMetaEl = document.getElementById("chatMeta");
    const resumeStripEl = document.getElementById("resumeStrip");
    const messagesEl = document.getElementById("messages");
    const promptInputEl = document.getElementById("promptInput");
    const mirrorToggleEl = document.getElementById("mirrorToggle");
    const composerEl = document.getElementById("composer");

    function escapeHtml(value) {{
      return value
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
    }}

    function setCurrentChat(chatId) {{
      state.currentChatId = Number(chatId);
      state.lastMessageKey = "";
      chatIdInputEl.value = String(chatId);
      refreshChatList();
      refreshChat();
    }}

    async function copyText(value) {{
      if (navigator.clipboard && navigator.clipboard.writeText) {{
        await navigator.clipboard.writeText(value);
        return;
      }}
      window.prompt("Copy command:", value);
    }}

    function renderResumeTargets(items) {{
      if (!items || items.length === 0) {{
        resumeStripEl.innerHTML = "";
        return;
      }}
      resumeStripEl.innerHTML = items.map(item => `
        <section class="resume-card">
          <div><strong>${{escapeHtml(item.provider)}}</strong> · ${{escapeHtml(item.bot)}}</div>
          <div class="subtle">${{escapeHtml(item.cwd || "")}}</div>
          <button type="button" data-command="${{escapeHtml(item.command)}}">Copy resume command</button>
        </section>
      `).join("");
      for (const button of resumeStripEl.querySelectorAll("button[data-command]")) {{
        button.addEventListener("click", async () => {{
          await copyText(button.getAttribute("data-command") || "");
        }});
      }}
    }}

    async function refreshChatList() {{
      const response = await fetch("/api/chats" + querySuffix);
      const payload = await response.json();
      chatListEl.innerHTML = "";
      for (const item of payload.chats) {{
        const button = document.createElement("button");
        button.type = "button";
        button.className = "chat-item" + (item.chat_id === state.currentChatId ? " active" : "");
        button.innerHTML = `
          <div><strong>${{item.chat_id}}</strong></div>
          <div class="subtle">${{escapeHtml(item.cwd || "no cwd")}}</div>
          <div class="subtle">messages: ${{item.message_count}}${{item.pending_approval ? " · pending approval" : ""}}</div>
        `;
        button.addEventListener("click", () => setCurrentChat(item.chat_id));
        chatListEl.appendChild(button);
      }}
    }}

    async function refreshChat() {{
      if (state.currentChatId === null || Number.isNaN(state.currentChatId)) {{
        messagesEl.innerHTML = "<div class='bubble system'>Enter a chat_id to start.</div>";
        return;
      }}
      const response = await fetch(`/api/chat?chat_id=${{encodeURIComponent(state.currentChatId)}}${{querySuffix ? "&" + querySuffix.slice(1) : ""}}`);
      const payload = await response.json();
      chatTitleEl.textContent = `Chat ${{payload.chat_id}}`;
      chatMetaEl.textContent = `cwd: ${{payload.cwd || "unknown"}} · session: ${{payload.session_id || "none"}}${{payload.pending_approval ? " · pending approval" : ""}}`;
      renderResumeTargets(payload.resume_targets || []);
      const messageKey = payload.messages.map(item => item.id).join(",");
      if (messageKey === state.lastMessageKey) {{
        return;
      }}
      state.lastMessageKey = messageKey;
      messagesEl.innerHTML = payload.messages.map(item => `
        <article class="bubble ${{item.role}}">
          <div class="meta">${{escapeHtml(item.role)}} · ${{escapeHtml(item.source)}} · ${{escapeHtml(item.created_at)}}</div>
          <div>${{escapeHtml(item.text)}}</div>
        </article>
      `).join("") || "<div class='bubble system'>No messages yet.</div>";
      messagesEl.scrollTop = messagesEl.scrollHeight;
      refreshChatList();
    }}

    composerEl.addEventListener("submit", async (event) => {{
      event.preventDefault();
      const prompt = promptInputEl.value.trim();
      const chatId = chatIdInputEl.value.trim();
      if (!chatId || !/^-?\\d+$/.test(chatId)) {{
        alert("Enter a numeric Telegram chat_id first.");
        return;
      }}
      if (!prompt) {{
        return;
      }}
      await fetch("/api/chat/send" + querySuffix, {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{
          chat_id: Number(chatId),
          prompt,
          mirror_to_telegram: mirrorToggleEl.checked,
        }}),
      }});
      promptInputEl.value = "";
      if (state.currentChatId !== Number(chatId)) {{
        setCurrentChat(Number(chatId));
        return;
      }}
      await refreshChat();
    }});

    chatIdInputEl.addEventListener("change", () => {{
      const value = chatIdInputEl.value.trim();
      if (/^-?\\d+$/.test(value)) {{
        setCurrentChat(Number(value));
      }}
    }});

    refreshChatList();
    setInterval(refreshChatList, 4000);
    setInterval(refreshChat, 2000);
  </script>
</body>
</html>"""
