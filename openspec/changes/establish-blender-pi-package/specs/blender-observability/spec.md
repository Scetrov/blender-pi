## ADDED Requirements

### Requirement: Current-scene inspection
The system SHALL provide bridge-owned structured inspection of Blender version, file state, active scene, mode, selection, objects, collections, materials, cameras, render settings, and supported diagnostics without requiring arbitrary Python trust. Inspections MUST read current Blender state when invoked and SHALL NOT rely on a shadow scene model.

#### Scenario: Artist changes selection manually
- **WHEN** the artist changes selection after an earlier inspection and Pi inspects again
- **THEN** the result reflects the current Blender selection rather than cached state

#### Scenario: Inspection result is large
- **WHEN** scene information exceeds inline limits
- **THEN** the bridge returns a bounded summary with pagination, cursors, or a structured artifact

### Requirement: Visual evidence capture
The system SHALL capture supported viewport, workbench, or rendered evidence from the open scene and return structured artifact descriptors. Capture operations SHALL identify relevant scene, view, camera, frame, render mode, dimensions, and timestamp so Pi and the artist can interpret the evidence.

#### Scenario: Pi requests viewport evidence
- **WHEN** the active Blender context supports viewport capture
- **THEN** the bridge creates an image artifact and reports its capture context

#### Scenario: Required visual context is unavailable
- **WHEN** capture requires an area, camera, engine, or context that is unavailable
- **THEN** the bridge returns an actionable structured error without fabricating evidence

### Requirement: Verified artifact handling
Large images, checkpoints, exports, and reports SHALL be represented by descriptors containing an opaque artifact ID, role, media type, canonical local path, byte size, and SHA-256 digest. The Pi extension MUST validate allowed location, existence, file type, and size before a bounded read, then verify the digest over the bytes read before exposing content to Pi or the model. Consumption MUST use those same verified bytes; reopening or replacing the file requires fresh validation.

#### Scenario: Valid image artifact is received
- **WHEN** an artifact descriptor references an allowed image with matching digest and size
- **THEN** Pi can attach the verified image to the tool result

#### Scenario: Descriptor escapes session directory
- **WHEN** a descriptor resolves outside allowed artifact or explicitly approved user paths
- **THEN** Pi refuses to read it and reports a path-validation error

#### Scenario: Artifact changes after creation
- **WHEN** the file's digest or size no longer matches its descriptor
- **THEN** Pi refuses the artifact as stale or tampered

### Requirement: Artist-visible bridge state
The Blender UI SHALL display listener state, pairing code when pending, paired client identity, trust level, active operation summary and phase, progress where known, checkpoint state, recent outcome, and controls to deny pairing, revoke trust, request cooperative cancellation, and locate recovery information.

#### Scenario: Mutation is active
- **WHEN** Pi is executing an operation
- **THEN** whenever Blender's event loop can service the UI, the artist can see the operation summary, effective risk, current phase, and available cancellation or recovery controls; during non-yielding execution the panel may remain stale or unavailable and Pi must distinguish acknowledged status from locally requested actions

#### Scenario: Trust is revoked
- **WHEN** the artist revokes the active session
- **THEN** after Blender processes the revocation action, the UI reflects unpaired state and no longer presents the client as authorized; active execution is signalled for cooperative cancellation, not claimed to have stopped

### Requirement: Actionable diagnostics
Pi and Blender SHALL expose diagnostics for bridge discovery, installation version, protocol negotiation, pairing, trust, queue state, main-thread scheduling, artifact directories, and recent bounded errors. Diagnostics MUST redact credentials and provide corrective actions where known.

#### Scenario: Pi cannot connect
- **WHEN** no compatible bridge is available
- **THEN** diagnostics distinguish not installed, not enabled, stale discovery, incompatible version, pairing required, and connection failure where evidence permits

### Requirement: Bounded telemetry and privacy
The initial implementation SHALL NOT transmit telemetry, prompts, scene data, code, receipts, or artifacts to a project-operated remote service. Local logs and diagnostics SHALL be bounded, redact credentials, and document their storage and deletion behavior.

#### Scenario: Operation runs normally
- **WHEN** Pi controls Blender
- **THEN** project code communicates only through the local bridge and user-requested external effects, with no undisclosed project telemetry
