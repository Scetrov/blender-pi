## ADDED Requirements

### Requirement: Length-framed JSON-RPC transport
The bridge protocol SHALL use JSON-RPC 2.0 messages encoded as UTF-8 JSON and framed by a four-byte unsigned big-endian payload length. Both peers MUST enforce configured frame-size limits, reject invalid encodings and malformed envelopes, and close or resynchronize connections according to documented protocol errors without allocating unbounded memory.

#### Scenario: Valid frame is received incrementally
- **WHEN** a complete frame arrives across multiple socket reads
- **THEN** the receiver reconstructs exactly one JSON-RPC message and dispatches it once

#### Scenario: Declared frame is oversized
- **WHEN** a frame length exceeds the negotiated maximum
- **THEN** the receiver rejects it before allocating the declared payload and records a bounded protocol error

#### Scenario: JSON-RPC envelope is invalid
- **WHEN** a frame contains valid JSON but an invalid request, response, or notification shape
- **THEN** it is not dispatched as a Blender operation and the peer receives the applicable structured error

### Requirement: Version and capability negotiation
The first authenticated session exchange SHALL negotiate protocol version, package version, bridge version, Blender version, maximum frame size, and supported capabilities. Incompatible major versions MUST fail closed; optional features MUST be enabled only when both peers advertise support.

#### Scenario: Compatible peers connect
- **WHEN** peers share a supported protocol major version and required capabilities
- **THEN** the session enters ready state with negotiated limits and capabilities

#### Scenario: Mandatory capability is absent
- **WHEN** a peer lacks a capability required for safe operation
- **THEN** the session does not enter ready state and reports the missing capability

### Requirement: Schema validation and stable errors
Every protocol method, result, notification, and error SHALL have a versioned schema and conformance fixture. Inputs MUST be validated before entering the Blender main-thread queue. Errors SHALL include a stable machine-readable code, safe message, correlation identifier, and optional bounded details without secrets or unbounded traceback data.

#### Scenario: Method parameters are invalid
- **WHEN** a request omits a required parameter or supplies the wrong type
- **THEN** it receives a validation error and no Blender work is scheduled

#### Scenario: Internal exception contains sensitive data
- **WHEN** an implementation exception includes a credential or oversized traceback
- **THEN** the protocol response redacts secrets and bounds diagnostic details while preserving a correlation identifier

### Requirement: Ordered mutation semantics
The bridge SHALL serialize scene-mutating requests through one ordered main-thread queue. Requests SHALL expose queued, active, completed, failed, or cancellation-requested states. Read-only metadata operations MAY remain responsive but MUST NOT observe or cause unsafe concurrent mutation.

#### Scenario: Two mutations arrive concurrently
- **WHEN** two authenticated mutation requests are accepted
- **THEN** they execute one at a time in deterministic queue order

#### Scenario: Connection drops during queued work
- **WHEN** the controlling connection closes before a queued mutation starts
- **THEN** the bridge cancels that queued mutation and does not silently transfer control to another client

### Requirement: Execution-time scene preconditions
Mutation requests SHALL carry the inspected file/session generation and operation-relevant target, mode, and selection preconditions. The bridge MUST validate these on the main thread immediately before execution, including after approval delays, and reject stale work rather than silently retargeting it. File replacement MUST invalidate queued mutations and inspection cursors. This requirement does not mandate a full scene hash or shadow scene model.

#### Scenario: Artist changes the target while approval is pending
- **WHEN** an operation's relevant target or context no longer matches its inspected preconditions after approval
- **THEN** execution is rejected as stale and Pi must inspect again before proposing a new mutation

#### Scenario: Artist loads another file with queued work
- **WHEN** the active file is replaced before a queued mutation starts
- **THEN** that mutation is invalidated and cannot execute against the replacement file

### Requirement: Ambiguous outcomes and mutation deduplication
Accepted mutations SHALL have client-supplied idempotency keys bound to the authenticated session and validated request content. Within the documented bounded retention window, duplicate keys MUST NOT execute a mutation twice and conflicting content MUST be rejected. Disconnect SHALL cancel queued work and request cooperative cancellation of active work, which may still complete. A bounded outcome ledger SHALL survive connection replacement within the bridge lifetime and permit reconciliation only after fresh pairing with appropriate trust. Pi MUST NOT automatically resubmit a mutation whose acceptance or outcome is ambiguous.

#### Scenario: Completion acknowledgement is lost
- **WHEN** a mutation executes but the connection drops before Pi receives its outcome
- **THEN** Pi re-pairs and queries the retained outcome rather than executing the mutation again

#### Scenario: Outcome cannot be reconciled
- **WHEN** the bridge restarted, its retention window expired, or acceptance cannot be established
- **THEN** Pi reports outcome unknown and requires fresh inspection and an explicit new decision before any retry

#### Scenario: Duplicate submission changes the code
- **WHEN** a retained idempotency key is reused with different validated request content
- **THEN** the bridge returns a conflict without scheduling the new code

### Requirement: Bidirectional notifications
The protocol SHALL support notifications for progress, logs, warnings, artifacts, trust changes, operation state, completion, and failure. Notifications MUST identify their operation or session, respect output limits, and preserve ordering within an operation.

#### Scenario: Operation reports progress
- **WHEN** executing code emits a progress update
- **THEN** Pi receives a structured notification with operation ID, phase, completed amount, optional total, and bounded message

#### Scenario: Notification exceeds limits
- **WHEN** a log or progress payload exceeds negotiated limits
- **THEN** it is truncated or rejected according to protocol rules without destabilizing the connection

### Requirement: Protocol conformance across languages
The TypeScript and Python implementations SHALL consume the same language-neutral framing, schema, and error fixtures. CI MUST detect incompatible serialization, framing, validation, and version behavior before release.

#### Scenario: Shared fixture suite runs
- **WHEN** protocol conformance tests execute in both implementations
- **THEN** each accepted and rejected fixture produces the documented equivalent outcome
