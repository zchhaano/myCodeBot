## ADDED Requirements

### Requirement: WhatsApp inbound message processing
The system SHALL accept inbound WhatsApp webhook events, validate them, normalize supported message types, and submit them to the bridge core.

#### Scenario: Receive a WhatsApp text message
- **WHEN** the WhatsApp webhook receives a valid text message event for a configured bridge number
- **THEN** the adapter normalizes the event into a bridge-core message and triggers the same prompt flow used by other channels

#### Scenario: Ignore unsupported webhook payloads safely
- **WHEN** the webhook receives an event type that the bridge does not support
- **THEN** the system acknowledges the webhook without mutating conversation state or crashing the process

### Requirement: WhatsApp outbound replies
The system SHALL send bridge responses back to the originating WhatsApp conversation using the configured WhatsApp provider API.

#### Scenario: Return assistant output to WhatsApp
- **WHEN** the bridge core yields assistant response text for a WhatsApp conversation
- **THEN** the adapter delivers the text back to the same WhatsApp conversation in provider-compliant message payloads

#### Scenario: Return bridge command feedback to WhatsApp
- **WHEN** a WhatsApp user invokes a supported bridge command
- **THEN** the adapter returns the command result text to that same WhatsApp conversation

### Requirement: WhatsApp media parity for supported types
The system SHALL support WhatsApp image and audio inputs using the existing bridge media pipeline for download, prompt preparation, and transcription.

#### Scenario: Process an inbound WhatsApp image
- **WHEN** a WhatsApp image message is received
- **THEN** the adapter downloads the media, stores it locally, and forwards it to the bridge using the same image-handling behavior used by existing channels

#### Scenario: Process an inbound WhatsApp audio message
- **WHEN** a WhatsApp audio or voice message is received
- **THEN** the adapter downloads the media, transcribes it through the existing media handler, and forwards the transcript to the bridge core

