## Why

The bridge currently treats Telegram as the only external chat channel, which makes the message flow, session storage, approvals, and local observability tightly coupled to Telegram-specific identifiers and APIs. Adding WhatsApp support requires a channel-agnostic core so new adapters can reuse the existing Claude/Codex runner, approval, project, and local resume flows instead of reimplementing them.

## What Changes

- Introduce a platform-neutral bridge core that handles message dispatch, command handling, session updates, approvals, project switching, resume command generation, and chat logging independently of Telegram transport details.
- Refactor the Telegram integration into an adapter layer that maps Telegram updates into the bridge core and renders core responses back to Telegram.
- Add a WhatsApp webhook adapter that can receive text and media messages, download supported media, and send responses through the configured WhatsApp provider.
- Make stored conversation state channel-aware so Telegram and WhatsApp sessions cannot collide and channel metadata is preserved in logs, approvals, and project bindings.
- Extend the local status and chat web UI to show channel-aware conversations and expose the same resume and inspection capabilities across supported channels.

## Capabilities

### New Capabilities
- `multi-channel-bridge-core`: Platform-neutral message processing, command handling, and channel-aware session state for external chat adapters.
- `whatsapp-channel`: Receive, process, and respond to WhatsApp conversations through a webhook-based adapter while reusing the existing bridge behavior.
- `channel-aware-local-observability`: Show channel metadata and channel-scoped conversations in the local status page and chat UI.

### Modified Capabilities
- None.

## Impact

- Affected code: `bot.py`, session/workdir/approval/chat log stores, status web UI, config loading, media ingestion, and local resume helpers.
- New code: bridge core module(s), WhatsApp adapter/webhook handler, channel-aware key utilities, and WhatsApp configuration surface.
- External systems: WhatsApp provider webhook verification, outbound message API calls, and media download endpoints.
- Operational impact: deployment will require webhook hosting and new credentials for the chosen WhatsApp provider in addition to existing Telegram configuration.
