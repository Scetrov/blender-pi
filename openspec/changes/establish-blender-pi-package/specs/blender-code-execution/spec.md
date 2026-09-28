## ADDED Requirements

### Requirement: Broad trusted Blender Python execution
A fully trusted paired session SHALL allow task-specific Python with `bpy` access equivalent to Blender's Run Script capability, including use of installed add-ons and Blender APIs required for modeling, geometry nodes, sculpting, texturing, shading, rigging, animation, simulation, rendering, and import/export. The UI and documentation MUST state that this capability is not sandboxed.

#### Scenario: Trusted modeling operation executes
- **WHEN** a fully trusted client submits valid Python that creates and shades Blender data
- **THEN** the bridge executes it against the artist's open scene and returns its structured outcome

#### Scenario: Untrusted session requests execution
- **WHEN** a client without full execution trust submits Python
- **THEN** execution is rejected before the code enters the main-thread queue

### Requirement: Main-thread execution
All Python that accesses Blender APIs SHALL execute on Blender's main thread through supported scheduling and operator mechanisms. Socket, framing, and other background threads or processes MUST NOT call `bpy`. The I/O architecture MUST pass a documented target-version support assessment and representative feasibility tests before adoption; avoiding `bpy` calls alone MUST NOT be treated as evidence that persistent Python threads are supported.

#### Scenario: Execution request arrives through the I/O component
- **WHEN** the selected I/O component validates an execution request
- **THEN** it queues plain request data and Blender API access begins only when the main-thread dispatcher accepts it

### Requirement: Fresh execution namespace
Every operation SHALL receive a fresh namespace containing documented bridge bindings and Blender modules while retaining scene state only through Blender data. Python locals and cached Blender references MUST NOT persist implicitly between operations.

#### Scenario: Consecutive operations reuse a local variable name
- **WHEN** a second operation starts after the first completes
- **THEN** the first operation's local variables are unavailable unless their state was explicitly stored in Blender or an approved job record

#### Scenario: Undo invalidates a datablock reference
- **WHEN** Blender undo occurs between operations
- **THEN** the next operation obtains current datablocks rather than reusing a cached Python reference

### Requirement: Structured interaction bindings
The execution namespace SHALL provide documented bindings for setting a JSON-compatible result, emitting bounded logs and warnings, reporting progress, registering artifacts, and checking cooperative cancellation. Plain stdout and stderr SHALL be captured separately with line and byte limits.

#### Scenario: Script returns structured measurements
- **WHEN** code sets a result containing JSON-compatible objects and common supported Blender value types
- **THEN** the bridge returns the normalized structured value without requiring output parsing

#### Scenario: Script produces excessive stdout
- **WHEN** captured stdout exceeds configured limits
- **THEN** the bridge truncates it, records truncation metadata, and keeps the complete operation result bounded

### Requirement: Deterministic result serialization
Results SHALL support JSON null, booleans, finite numbers, strings, arrays, and string-keyed objects. Documented Blender math values and datablock references MAY be normalized into stable JSON forms. Unsupported values, non-finite numbers, cycles, or excessive depth MUST produce a structured serialization error rather than an implicit representation.

#### Scenario: Result contains a Blender vector
- **WHEN** a script returns a supported `mathutils.Vector`
- **THEN** the result contains its documented numeric array representation

#### Scenario: Result contains an unsupported Python object
- **WHEN** a script returns an object without a documented serializer
- **THEN** execution reports a serialization error identifying the unsupported type without leaking arbitrary object contents

### Requirement: Cooperative progress and cancellation
Longer operations SHALL support staged progress and cooperative cancellation checks. The protocol SHALL distinguish cancellation requested by the caller, received by the bridge, and observed by execution. The bridge SHALL mark cancellation-requested when it receives the request without waiting for the main-thread dispatch queue; no acknowledgement MUST imply that execution has stopped. The system MUST NOT claim it can forcibly terminate arbitrary Python safely. Workflows advertised as responsive SHALL return control to Blender's event loop between bounded stages or use supported tracked jobs; progress emission and cancellation checks alone do not provide UI responsiveness.

#### Scenario: Cooperative script receives cancellation
- **WHEN** the artist or Pi requests cancellation and the script checks cancellation state
- **THEN** execution stops at the check, reports cancellation, and follows undo or checkpoint recovery policy

#### Scenario: Non-cooperative script blocks
- **WHEN** arbitrary Python does not yield or check cancellation
- **THEN** Pi reports the latest acknowledged cancellation state without claiming termination, and documentation warns that Blender's UI and controls may remain unavailable until execution yields

#### Scenario: Native execution delays cancellation delivery
- **WHEN** a native call prevents the Python I/O component from receiving a cancellation request promptly
- **THEN** Pi distinguishes its locally requested cancellation from bridge acknowledgement and does not claim that the bridge has received or observed it

### Requirement: Tracked asynchronous job ownership
Supported asynchronous Blender jobs SHALL be registered to an owning operation before launch. The operation SHALL retain its mutation slot until the job reaches a tracked terminal state, and SHALL finalize its receipt and final artifacts only then. Job adapters MUST define completion, failure, cancellation, disconnect, and file-load behavior. Only documented non-mutating status and cancellation operations MAY proceed while the slot is held. Unregistered asynchronous work MUST be identified as outside managed lifecycle and recovery guarantees.

#### Scenario: Render launch returns before completion
- **WHEN** a supported asynchronous render returns control to its launching script while still running
- **THEN** the owning operation remains active, subsequent mutations remain blocked, and final receipt/artifacts are not reported until tracked termination

#### Scenario: Tracked job is interrupted by file replacement
- **WHEN** a file load interrupts an active tracked job
- **THEN** its adapter records the interrupted or unknown outcome, prevents stale callbacks from changing the new scene, and releases ownership only after safe cleanup

### Requirement: Structured failure behavior
Compile errors, runtime exceptions, cancellation, serialization failures, and bridge failures SHALL produce distinct structured outcomes with bounded safe tracebacks, operation receipts, and recovery metadata. A failed request MUST NOT be reported as successful merely because a result object was returned.

#### Scenario: Python raises an exception
- **WHEN** trusted code raises during execution
- **THEN** the operation enters failed state with a safe traceback, captured output, undo/checkpoint status, and correlation identifiers
