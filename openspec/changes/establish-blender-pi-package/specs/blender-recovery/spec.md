## ADDED Requirements

### Requirement: Declared and effective operation risk
Every mutation request SHALL include an artist-readable summary, declared risk, expected effects, undo preference, and checkpoint policy. The bridge SHALL compute an effective risk that can retain or escalate but MUST NOT silently downgrade declared or bridge-known risk. Unrestricted Python does not have a safety proof; lack of a heuristic match MUST NOT be reported as proof that code has no external effects.

#### Scenario: Request omits risk metadata
- **WHEN** a mutation request lacks required risk or effect declarations
- **THEN** it is rejected before execution with a validation error

#### Scenario: Analysis detects elevated effects
- **WHEN** a request declared moderate risk but bridge-owned analysis detects destructive or external behavior
- **THEN** effective risk is escalated and the stronger recovery or approval policy applies

### Requirement: Blender-native undo integration
Supported mutations SHALL run through a bridge-owned Blender operator configured for ordinary Blender undo and use the request summary to create a meaningful undo entry. The system MUST NOT represent manual `undo_push` calls as a universal transaction mechanism.

#### Scenario: Undoable operation succeeds
- **WHEN** a supported scene mutation completes successfully
- **THEN** Blender exposes one meaningful Pi-labeled undo step for the operation

#### Scenario: Failed operation partially mutates data
- **WHEN** execution fails after changing Blender data
- **THEN** the receipt reports failure and actual undo availability, independently of Blender operator return status; where preserving the undo step requires the wrapper to return `FINISHED`, that return MUST NOT turn the operation receipt into success

### Requirement: Mandatory checkpoints for elevated risk
Declared or clearly detected high-risk scene mutations SHALL create and verify a checkpoint before execution. Unknown effects alone do not require a checkpoint; artists MAY request one explicitly. Checkpoint failure MUST block the operation. Checkpoints SHALL use collision-resistant names, preserve source-scene identity metadata, avoid silently replacing the artist's active file, and follow a documented location and retention policy. The verified recovery scope MUST document behavior for unsaved files, relative asset paths, and external caches; a `.blend` checkpoint MUST NOT be presented as restoring external files it does not contain.

#### Scenario: High-risk operation has a verified checkpoint
- **WHEN** a high-risk request is ready to execute
- **THEN** the bridge records a verified checkpoint descriptor before beginning mutation

#### Scenario: Checkpoint cannot be created
- **WHEN** storage, permissions, or Blender state prevents checkpoint creation
- **THEN** the high-risk operation does not execute and the artist receives a recovery-focused error

### Requirement: Explicit approval for external effects
Operations with declared or clearly detected destructive external effects that overwrite user files, delete broad filesystem targets, launch external processes, expose data over a network, change installation state, or perform other documented hazards SHALL require explicit artist approval unless a future narrowly scoped policy has already authorized that exact effect. Known targets SHALL be displayed; if an obvious hazard's target cannot be established, approval SHALL identify that uncertainty rather than invent a target. Routine full-trust Blender Python does not require recurring approval merely because arbitrary Python could theoretically have unknown effects. Pairing alone MUST NOT imply approval for declared or detected obvious hazards. UI and documentation MUST describe these as advisory pre-execution checks, not enforceable per-effect mediation: undeclared or indirect effects may escape detection inside unrestricted Python, which Blender does not sandbox.

#### Scenario: Script intends to overwrite an export
- **WHEN** expected effects identify replacement of an existing external file
- **THEN** execution pauses for approval showing the target and effect

#### Scenario: Artist denies external effect
- **WHEN** the artist rejects the requested effect
- **THEN** the operation is cancelled before its code executes

#### Scenario: Routine trusted code has no obvious hazard
- **WHEN** a fully trusted client submits ordinary Blender code with no declared or clearly detected destructive external effect
- **THEN** the bridge does not demand an uncertainty approval or mandatory checkpoint solely because arbitrary Python cannot be proven safe

#### Scenario: Obvious destructive effect has an unknown target
- **WHEN** an operation clearly attempts broad filesystem deletion but its target cannot be identified reliably
- **THEN** the bridge asks for explicit approval describing the hazard and unknown target without claiming its detector is complete

### Requirement: Operation receipts
Every accepted mutation SHALL produce a bounded receipt recording operation and correlation IDs, timestamps, summary, declared and effective risk, expected effects, trust state, outcome, duration, undo state, checkpoint descriptor, warnings, artifact references, truncation metadata, and structured error details. Receipts MUST redact pairing codes, credentials, and detected secrets.

#### Scenario: Operation completes successfully
- **WHEN** a mutation completes
- **THEN** Pi and Blender can present a receipt sufficient to understand the change and available recovery paths

#### Scenario: Receipt input contains session credential
- **WHEN** logs or errors include the active credential
- **THEN** the stored and transmitted receipt contains a redacted value

### Requirement: Artist-confirmed checkpoint restore
Checkpoint restoration SHALL require explicit artist confirmation, identify the scene and operation being replaced, and warn about unsaved changes. Restore outcomes SHALL themselves be recorded without deleting the source checkpoint automatically.

#### Scenario: Artist confirms restore
- **WHEN** the artist approves restoration of a valid checkpoint
- **THEN** Blender restores it using the documented workflow and records whether the restore completed

#### Scenario: Current scene has unsaved changes
- **WHEN** restore is requested while current work may be lost
- **THEN** Blender presents that risk and does not restore until the artist explicitly confirms
