## 1. Extract bridge core primitives

- [x] 1.1 Define normalized inbound message, outbound action, and channel conversation key types for transport-neutral bridge processing
- [x] 1.2 Move command routing, prompt execution, approvals, project switching, and chat-log updates out of `bot.py` into a reusable bridge core module
- [x] 1.3 Add focused smoke tests or verification scripts that prove the refactored core preserves current Telegram behavior

## 2. Make persistence channel-aware

- [x] 2.1 Update session, approval, workdir, and chat-log persistence to use channel-scoped conversation identifiers
- [x] 2.2 Add backward-compatible loading or migration handling for existing Telegram-only stored data
- [x] 2.3 Extend local resume helpers to resolve and format channel-aware conversation targets

## 3. Refactor Telegram onto the new core

- [x] 3.1 Introduce a Telegram adapter layer that normalizes Telegram updates and delegates handling to the bridge core
- [x] 3.2 Route Telegram command responses, streaming updates, and media handling through adapter-to-core boundaries instead of direct `bot.py` logic
- [x] 3.3 Verify `/project`, `/approve`, `/resume_local`, image handling, and voice transcription still behave correctly for Telegram conversations

## 4. Add WhatsApp adapter support

- [x] 4.1 Add WhatsApp configuration and startup validation for provider credentials, webhook verification, and outbound API settings
- [x] 4.2 Implement WhatsApp webhook request handling, event normalization, and unsupported-event filtering
- [x] 4.3 Implement WhatsApp outbound text replies and media download flows using the existing media handler pipeline
- [x] 4.4 Connect WhatsApp conversations to the bridge core so text, image, audio, project, approval, and resume flows reuse existing logic

## 5. Extend local observability for multiple channels

- [x] 5.1 Update status and chat APIs to expose channel metadata, channel-scoped conversation identifiers, and per-channel resume targets
- [x] 5.2 Update the local chat UI to display channel attribution and operate on Telegram and WhatsApp conversations without ambiguity
- [x] 5.3 Ensure local-web-originated messages append to the correct channel-scoped conversation history

## 6. Validate and document rollout

- [x] 6.1 Run end-to-end validation for Telegram after the core refactor and for WhatsApp after adapter integration
- [x] 6.2 Document WhatsApp setup, required secrets, webhook hosting expectations, and operational restart steps in the repository docs
- [x] 6.3 Document rollback/disable steps so WhatsApp can be turned off without breaking Telegram service
