## ADDED Requirements

### Requirement: Loopback-only discovery
The Blender bridge SHALL listen only on literal loopback addresses and SHALL publish a bounded, owner-readable discovery descriptor containing endpoint and bridge identity but no bearer credential. The bridge MUST reject non-loopback connections and invalid endpoint metadata.

#### Scenario: Pi discovers a running bridge
- **WHEN** the bridge is enabled for pairing
- **THEN** Pi can discover its loopback endpoint and version without receiving an authenticated session credential

#### Scenario: Remote host attempts connection
- **WHEN** a connection originates outside the loopback interface
- **THEN** the bridge refuses the connection before pairing or command processing

### Requirement: Short-lived physical-presence pairing
The bridge SHALL generate a cryptographically random pending pairing identifier and short-lived human-enterable code. Codes MUST be single-use, attempt-limited, rate-limited, excluded from logs, and invalidated by expiry, successful use, bridge restart, or excessive failures.

#### Scenario: Correct code is entered in time
- **WHEN** Pi submits a valid unused code before expiry
- **THEN** Blender presents the pairing request for explicit artist approval without yet granting full trust

#### Scenario: Code is guessed repeatedly
- **WHEN** a caller exceeds the allowed failed attempts
- **THEN** the pending code is invalidated and further attempts require a newly generated code

#### Scenario: Code has expired
- **WHEN** Pi submits an expired code
- **THEN** the bridge denies pairing without revealing whether other credential material was valid

### Requirement: Explicit Blender-side approval
Pairing SHALL complete only after Blender displays the requesting client name, package version, working directory, requested trust level, and expiry and the artist explicitly approves it. Denial or dismissal MUST leave the client unauthenticated.

#### Scenario: Artist allows the session
- **WHEN** the artist reviews a pending request and selects Allow Session
- **THEN** the bridge consumes the pairing code and issues a new cryptographically random session credential

#### Scenario: Artist denies the request
- **WHEN** the artist rejects or dismisses the request
- **THEN** no session credential is issued and the denial is visible to Pi without exposing sensitive data

### Requirement: Ephemeral authenticated sessions
Session credentials SHALL remain in process memory, SHALL NOT be written into discovery descriptors or logs, and SHALL be revoked on bridge stop, explicit artist revocation, credential replacement, or security-relevant session teardown. Every privileged request MUST be bound to an active authenticated session and trust level.

#### Scenario: Blender restarts
- **WHEN** Blender or the bridge restarts after pairing
- **THEN** the prior credential no longer authorizes requests and a new pairing is required

#### Scenario: Artist revokes trust
- **WHEN** the artist selects Revoke in Blender
- **THEN** pending and subsequent privileged requests for that session are rejected

### Requirement: Separate inspection and full trust states
The bridge SHALL distinguish bridge-owned inspection capability from full trusted Python execution. Arbitrary Python MUST NOT be represented as safe or read-only, and full trust SHALL be visibly identified as Run Script-equivalent authority.

#### Scenario: Client has inspection trust only
- **WHEN** Pi requests arbitrary Python execution without full trust
- **THEN** the bridge denies execution while allowing only documented bridge-owned inspection methods

#### Scenario: Full trust is requested
- **WHEN** a pairing request asks for full execution trust
- **THEN** Blender warns that code can access Blender data and operating-system resources before approval
