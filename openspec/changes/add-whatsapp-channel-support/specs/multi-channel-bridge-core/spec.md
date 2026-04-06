## ADDED Requirements

### Requirement: Channel-scoped conversation state
The system SHALL store conversation sessions, project bindings, approvals, and chat history using channel-scoped conversation identifiers so that two channels with the same raw chat identifier cannot overwrite each other.

#### Scenario: Persist Telegram and WhatsApp conversations independently
- **WHEN** Telegram and WhatsApp both send messages whose raw chat identifier resolves to the same numeric value
- **THEN** the system stores independent session, approval, workdir, and chat-log records for each channel

#### Scenario: Load existing channel-scoped state on resume
- **WHEN** a follow-up message arrives for an existing channel conversation
- **THEN** the system resumes the stored backend session and project binding associated with that channel-scoped conversation identifier

### Requirement: Adapter-independent command handling
The system SHALL expose a transport-neutral bridge core that handles supported bridge commands and prompt execution without depending on Telegram-specific request or response formats.

#### Scenario: Channel adapter forwards text to bridge core
- **WHEN** a supported channel adapter receives a user text message
- **THEN** it can submit the normalized message to the bridge core and receive normalized responses without duplicating prompt execution logic

#### Scenario: Bridge commands behave consistently across channels
- **WHEN** a supported channel sends a command such as project switching, approval continuation, or local resume lookup
- **THEN** the bridge core applies the same command behavior and state transitions regardless of which adapter submitted the command

### Requirement: Channel metadata in chat history
The system SHALL record the source channel for every stored user, assistant, and system chat log entry.

#### Scenario: Local chat view includes channel attribution
- **WHEN** the local chat UI or status API reads stored messages
- **THEN** each message includes the originating channel metadata needed to distinguish Telegram, WhatsApp, and local web activity

