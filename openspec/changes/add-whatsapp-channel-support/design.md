## Context

The current bridge grew around a single Telegram polling loop in `bot.py`. Transport concerns, message normalization, command handling, approvals, project switching, session persistence, and runner invocation are all wired together around Telegram-specific concepts such as Telegram chat IDs and Telegram API request/response handling. The repository now also has local web chat and resume helpers that assume one external channel but already expose shared bridge behavior worth reusing.

Adding WhatsApp support is not just another inbound API client. It introduces a webhook-style adapter, a second external message identity namespace, new media download and outbound delivery mechanics, and a need to preserve consistent command semantics across channels. The design must avoid cloning Telegram logic into a parallel WhatsApp implementation because that would fork the command surface, approval behavior, and session model immediately.

## Goals / Non-Goals

**Goals:**
- Introduce a bridge core layer that owns command routing, prompt execution, approvals, project switching, chat logging, and session updates independently of any transport.
- Make conversation persistence channel-aware so Telegram and WhatsApp sessions can coexist safely.
- Add a webhook-oriented WhatsApp adapter that reuses existing runner, media, approval, and resume functionality.
- Extend local status and chat surfaces to expose channel-aware conversation metadata.
- Preserve current Telegram behavior while refactoring toward the new core.

**Non-Goals:**
- Replacing the existing Claude/Codex runner model or switching the bridge to interactive TUI transport.
- Designing for every possible external channel in the first iteration beyond Telegram and WhatsApp.
- Building a full multi-tenant admin console or authentication layer for the local web UI.
- Supporting unsupported WhatsApp message types beyond text, images, and audio in the first pass.

## Decisions

### 1. Extract a transport-neutral BridgeCore

The refactor will introduce a `BridgeCore` service that accepts normalized inbound messages and emits normalized outbound actions. Telegram and WhatsApp adapters will translate platform payloads into a shared message shape and delegate the rest of the behavior to the core.

Why this over duplicating `bot.py`:
- It keeps `/project`, `/approve`, `/resume_local`, and prompt execution semantics defined in one place.
- It allows the WhatsApp adapter to reuse the existing session, approval, workdir, media, and resume code immediately.
- It reduces future cost for additional channels and local testing.

Alternative considered:
- Clone `bot.py` into `whatsapp_bot.py` and adjust API calls. Rejected because every future command or persistence change would need to be mirrored manually across transports.

### 2. Introduce channel-scoped conversation identifiers

Session, approval, workdir, and chat-log persistence will move from raw Telegram chat IDs to stable composite keys such as `telegram:<chat-id>` and `whatsapp:<conversation-id>`. Internally, the core will treat this as the canonical conversation key.

Why this over provider-specific stores:
- It avoids key collisions with minimal storage migration complexity.
- Existing JSON-backed stores can remain in place with modest schema changes.
- It makes status and resume tooling channel-aware without introducing a database.

Alternative considered:
- Separate state files per transport. Rejected because command handling, local observability, and resume logic still need a common way to address conversations across channels.

### 3. Keep adapters thin and transport-specific

Telegram stays as a polling adapter. WhatsApp will be introduced as a webhook adapter with provider-specific verification, inbound event parsing, media download, and outbound reply calls. Both adapters will be responsible only for transport translation and delivery.

Why this over unifying transport code too aggressively:
- Telegram polling and WhatsApp webhook flows are operationally different.
- Thin adapters let us preserve proven transport-specific code while consolidating business logic in the core.
- It keeps provider secrets and verification logic isolated from bridge behavior.

Alternative considered:
- Rebuild the whole app around a single generic HTTP server abstraction immediately. Rejected for the first iteration because it adds migration risk before core behavior is stabilized.

### 4. Reuse the existing media and runner pipelines

WhatsApp image and audio handling will flow through the current media download, transcription, and runner invocation code paths after the adapter normalizes the input. Resume command generation will also keep using the local helper logic, extended to understand channel-scoped sessions.

Why this over channel-specific media logic:
- The repository already has image prompt construction and voice transcription behavior that should remain consistent.
- This minimizes behavioral drift between Telegram, WhatsApp, and local web submissions.

Alternative considered:
- Build separate WhatsApp-only media handling. Rejected because it would duplicate tested behavior and complicate support.

### 5. Extend local status and chat views after the core refactor

The local status page and chat UI will be updated after channel-aware core and persistence land. They will surface channel labels, channel-scoped conversation identifiers, and channel-specific resume targets.

Why this sequence:
- The UI depends on the new persistence model and core addressing scheme.
- Updating the UI first would force temporary compatibility code that would be thrown away once the refactor lands.

Alternative considered:
- Leave the local UI unchanged for the first iteration. Rejected because channel-aware inspection is part of operability for the new WhatsApp adapter.

## Risks / Trade-offs

- [Core extraction touches most of `bot.py`] → Mitigation: refactor incrementally, preserve existing Telegram behavior with focused smoke tests before enabling WhatsApp.
- [JSON store schema migration can strand existing sessions] → Mitigation: support backward-compatible reads of old Telegram-only keys and migrate opportunistically on write.
- [Webhook deployment differs from Telegram polling] → Mitigation: isolate WhatsApp webhook handling behind dedicated config and handler modules, with clear startup validation for missing secrets.
- [Two channels increase command-surface expectations] → Mitigation: define a single normalized command router in the core and reuse it across adapters.
- [Local status and chat UI may become noisy with cross-channel data] → Mitigation: include explicit channel metadata and filtering/grouping in the UI/API payloads.

## Migration Plan

1. Extract `BridgeCore` and supporting normalized message/action types while keeping Telegram as the only active adapter.
2. Update stores and resume helpers to support channel-scoped keys, including backward-compatible handling of existing Telegram session data.
3. Refactor the Telegram adapter to call the core and verify existing commands and prompt flow still work.
4. Add the WhatsApp webhook adapter, provider configuration, and media download/outbound reply support.
5. Extend local status/chat APIs and UI with channel-aware conversation metadata.
6. Validate end-to-end flows for Telegram and WhatsApp, then document provider setup and operational restart requirements.

Rollback strategy:
- Keep the Telegram adapter operational during refactor and release the WhatsApp adapter behind explicit configuration.
- If WhatsApp rollout fails, disable only the WhatsApp adapter config and keep Telegram on the new core.

## Open Questions

- Which WhatsApp provider should be the first supported target: Meta Cloud API directly or a gateway such as Twilio?
- Should inbound webhook handling live inside the existing status server process or move to a dedicated FastAPI/HTTP app once WhatsApp lands?
- How much backward-compatibility is required for existing `sessions.json` and `chat_log.json` files versus a one-time migration script?
