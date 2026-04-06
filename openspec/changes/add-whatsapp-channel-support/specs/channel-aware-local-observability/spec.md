## ADDED Requirements

### Requirement: Channel-aware status and chat APIs
The local status page and chat API SHALL expose channel metadata for stored conversations and channel-specific resume targets.

#### Scenario: List conversations with channel context
- **WHEN** the local status or chat listing API returns known conversations
- **THEN** each conversation entry includes the channel identifier and enough metadata to distinguish otherwise similar chat identifiers

#### Scenario: Return local resume targets for each channel conversation
- **WHEN** the local chat API returns the detail view for a conversation
- **THEN** the response includes local resume command metadata for every available backend session associated with that channel conversation

### Requirement: Local chat UI supports multiple external channels
The local chat UI SHALL let the operator inspect and continue conversations for supported channels without losing channel attribution.

#### Scenario: Inspect a WhatsApp conversation in the local chat UI
- **WHEN** the operator opens a WhatsApp-backed conversation in the local chat UI
- **THEN** the UI shows that the conversation belongs to WhatsApp and displays the stored message history with channel-aware metadata

#### Scenario: Continue a channel conversation from the local web UI
- **WHEN** the operator submits a message through the local chat UI for a selected external conversation
- **THEN** the bridge appends the local message to that channel-scoped conversation and routes execution through the stored backend session

