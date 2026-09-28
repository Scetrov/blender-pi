## Context

The repository currently contains OpenSpec scaffolding but no product implementation. The intended users are Blender artists who retain creative control of an open Blender session while Pi performs repetitive construction, inspection, repair, and iteration. Pi and Blender run on the same workstation under the same operating-system user.

The system crosses two runtimes and trust boundaries:

- a TypeScript extension running inside Pi, with Pi's process permissions and native tool APIs;
- a Python extension running inside Blender 5.2+, where Blender data access must occur on the main thread;
- a local authenticated transport connecting those processes;
- generated Python which, after explicit trust, has Run Script-equivalent authority and is not sandboxed.

The live `.blend` must remain authoritative because artists may edit the scene manually between agent operations. The system must not maintain a competing scene representation. It must support broad Blender capabilities rather than continually duplicating `bpy` as a large catalog of constrained tools.

The repository must be publishable to npm for discovery on pi.dev, distribute the Blender extension through npm and GitHub releases, and begin with credible open-source governance and supply-chain controls. Pi-side code, skills, protocol material, and documentation are intended to be MIT-licensed; the Blender extension under `bridge/` is GPL-3.0-only. Package metadata and shipped artifacts must clearly identify this split and include the bridge's corresponding source and notices. Official publication on `extensions.blender.org` is not an initial distribution target.

## Goals / Non-Goals

**Goals:**

- Provide a Pi-native package that controls an artist's visible, open Blender 5.2+ session.
- Support the complete practical Blender automation surface through trusted Python, `bpy`, and installed add-ons.
- Keep setup understandable and establish trust through short-lived physical-presence pairing approved in Blender.
- Exchange validated, structured JSON messages for requests, results, progress, logs, errors, cancellation, and artifacts.
- Preserve Blender responsiveness by separating network I/O from main-thread Blender work and serializing mutations.
- Use ordinary Blender undo where supported and automatically checkpoint declared or detected high-risk scene operations.
- Give the artist visible operation status, meaningful undo labels, recovery information, and visual evidence.
- Provide focused skills that teach Pi safe and effective Blender workflows without placing a full Blender manual in every prompt.
- Ship a complete, testable, supply-chain-conscious repository with truthful OpenSSF Best Practices evidence.

**Non-Goals:**

- Implementing or wrapping an MCP server.
- Supporting generic non-Pi agent clients in the initial release.
- Reproducing every Blender operation as a dedicated Pi or bridge method.
- Maintaining a declarative or synchronized shadow copy of the Blender scene.
- Supporting Blender versions earlier than 5.2.
- Providing a security sandbox for trusted generated Python.
- Guaranteeing forced termination of arbitrary Python executing on Blender's main thread.
- Using a cloud relay, accepting remote-network connections, or enabling unattended remote control.
- Making headless Blender the primary workflow.
- Publishing the Blender extension through the official Blender Extensions marketplace.
- Generating finished creative work without artist direction and review.

## Decisions

### 1. Use one repository with independently testable components

The repository will contain:

```text
extensions/        Pi-native TypeScript extension
skills/            Agent Skills-compatible Blender workflow guidance
bridge/            Blender 5.2+ Python extension and packaging metadata
protocol/          Versioned JSON schemas and protocol fixtures
tests/             Cross-component and integration fixtures
docs/              Architecture, protocol, threat model, recovery, and release docs
.github/            CI, release, policy, and contribution automation
```

The npm package will include the Pi extension, skills, protocol material required at runtime, and an installable Blender extension archive or reproducibly packageable bridge source. Components share a release version while negotiating a separate protocol version.

A monorepo keeps protocol, package, bridge, tests, release notes, and security documentation in review together. Separate repositories were rejected because they increase version skew and make atomic security fixes harder. Keep the GPL bridge thin: it owns Blender-only UI, authentication, policy enforcement, main-thread `bpy` dispatch, undo, checkpointing, inspection, and artifact creation; Pi owns agent-facing workflows and UX. Shared wire contracts are MIT-licensed and contain no copied Blender implementation. A thin bridge does not weaken mandatory Blender-side trust or recovery checks.

### 2. Make the Pi extension the agent-facing control plane

The Pi extension will register a small stable tool surface for connection status, pairing, inspection, trusted execution, visual capture, job status, cancellation, and recovery. Common bridge-owned operations may be added for safety and ergonomics, but they do not define the limit of Blender capability.

The extension will manage connection lifecycle from Pi session events, truncate model-facing output, preserve structured details for rendering, and convert artifact descriptors into Pi text or image content. Long-lived resources will start only when a session or explicit command needs them and will close idempotently on session shutdown.

A separate MCP process was rejected because Pi already supplies typed tools, lifecycle management, UI, and package distribution. Adding MCP would add configuration and failure modes without increasing the initial product's capability.

### 3. Use framed JSON-RPC 2.0 over loopback TCP

Pi and Blender will maintain a bidirectional connection bound only to literal loopback addresses. Each frame consists of a four-byte unsigned big-endian payload length followed by UTF-8 JSON. Implementations will reject oversized, malformed, duplicate, or schema-invalid messages before dispatch.

JSON-RPC requests and responses cover bounded calls; notifications carry progress, logs, artifacts, trust changes, and operation completion. Request IDs and operation IDs are distinct so accepted long-running work can outlive the initiating request. Protocol schemas will be versioned and accompanied by language-neutral conformance fixtures.

The initial handshake communicates protocol version, package and bridge versions, Blender version, maximum frame size, and supported capabilities. Incompatible major protocol versions fail closed with an actionable diagnostic; optional features use capability negotiation.

HTTP was rejected because streaming and bidirectional notifications become awkward. WebSocket was rejected because browser interoperability is unnecessary and a correct implementation would add complexity or a bundled Python dependency. Newline-delimited JSON was rejected in favor of explicit framing and bounded allocation.

### 4. Use physical-presence pairing with ephemeral session trust

On startup, the Blender bridge listens on an ephemeral loopback port, creates a pending pairing identifier and short-lived one-time code, and writes a discovery descriptor without a bearer credential to an owner-readable user-scoped location. Blender displays the code and bridge status.

Pi submits the code and client metadata. Blender displays the requesting package identity, version, working directory, requested trust level, and expiry. Only explicit approval in Blender completes pairing. Successful approval consumes the code and issues a cryptographically random session credential that remains in process memory. Pairing codes expire, permit few attempts, are rate-limited, and are never logged.

The authenticated session credential is required for subsequent control messages and is revoked when the bridge stops, the artist revokes it, or the authenticated connection is replaced. The initial release will not provide permanent remembered clients.

This design protects against accidental and unauthorized local callers while keeping setup convenient. It does not claim to defend against a process already able to compromise the artist's operating-system account. A bespoke Diffie-Hellman or home-grown encryption scheme was rejected; stronger local-adversary protection would require a separately reviewed authenticated protocol.

### 5. Validate the I/O architecture and dispatch Blender work through the main thread

The I/O architecture is subject to an early feasibility gate: keeping `bpy` off a persistent Python thread does not establish that the thread is supported by Blender. Before adopting in-process background I/O, assess the target Blender version's documented threading support and exercise networking alongside Cycles rendering, Python drivers, file loads, and shutdown. A short passing stress test is not proof of support. If a supportable in-process design cannot be established, select process-isolated I/O or another documented mechanism and record its lifecycle and responsiveness limits before implementing the bridge.

The selected I/O component owns sockets and framing and never calls `bpy`. Implementation is staged to avoid a pairing/transport cycle: first provide fail-closed public handshake/pairing transport and bounded IPC/dispatch; then implement pairing, credentials, and trust; finally integrate authenticated gating and response writing before admitting privileged methods. Valid requests enter a bounded dispatch queue drained on Blender's main thread through supported scheduling mechanisms. Scene-mutating operations execute sequentially. Cancellation must reach a thread/process-safe signal independently of the main-thread work queue; Python I/O itself may be delayed by native calls retaining the GIL.

Each execution receives a fresh namespace with `bpy`, relevant safe conveniences, and an injected bridge interaction object. Blender scene state persists; Python locals and cached Blender references do not persist between executions. This avoids stale references after undo, deletion, file load, or datablock replacement.

The injected object provides structured result assignment, logging, progress, artifact registration, warning reporting, and cooperative cancellation checks. Standard output and error are captured with explicit byte and line limits. Scripts must return JSON-compatible values; common Blender math values and datablock references may be normalized into documented JSON forms. Unsupported values produce a serialization error rather than an unreliable string representation.

Python threads calling Blender APIs were rejected because Blender documents its Python integration as not thread-safe; persistent non-`bpy` threads also remain subject to the feasibility gate above. A persistent shared execution namespace was rejected because hidden mutable state and stale Blender references undermine recovery and reproducibility.

### 6. Treat trusted execution as Run Script-equivalent authority

Full-trust execution permits imports and broad Python/`bpy` use so tasks can cover modeling, nodes, shading, texturing, animation, simulation, rendering, import/export, and installed add-ons. It is not presented as a sandbox. Documentation and Blender UI will state that trusted code may access files, network libraries, subprocess APIs, credentials available to Blender, and other user resources.

A genuine inspection-only trust state uses bridge-owned read-only methods; it does not attempt to make arbitrary Python read-only. AST blocklists and restricted built-ins were rejected as security boundaries because Python restrictions are bypassable and would give users false confidence.

Execution requests include an artist-readable summary, declared risk, expected effects, undo preference, and checkpoint policy. These declarations support transparency and policy but do not establish that code is safe.

### 7. Use ordinary undo first and checkpoints for elevated risk

Where Blender supports it, generated mutations run inside a bridge-owned operator with `REGISTER` and `UNDO`, producing one meaningful undo entry such as `Pi: Generate roof tiles`. Implementations will not rely on `bpy.ops.ed.undo_push()` as a general transaction mechanism.

Operations are classified as low, moderate, high, external-effect, or unknown. Full-trust pairing is the normal authorization for routine Blender Python: low-risk work executes through ordinary undo without repeated approval, and moderate work adds a detailed receipt. Declared or clearly detected high-risk **scene** mutations require a verified checkpoint. Declared or clearly detected destructive external effects (such as user-file overwrite, broad filesystem deletion, process launch, network disclosure or installation changes) require explicit Blender approval showing the effect and known target; if an obvious hazard has no reliably identified target, show that uncertainty in the approval instead of inventing a target. Unknown effects alone do not imply a mandatory checkpoint or recurring approval. Pattern detection may escalate risk but is advisory and cannot establish safety or prevent indirect behavior. Do not scan arbitrary Python as though absence of a match proves effects are confined to Blender. Full trust remains Run Script-equivalent authority, not a Blender sandbox, and pairing is not per-operation approval for a declared or detected hazard.

Checkpoints are independent of the active scene's save history, use collision-resistant names, record source file and operation metadata, and are subject to a documented retention policy. Checkpoint creation failure prevents high-risk execution. Restoring a checkpoint requires artist confirmation.

Heuristic code analysis may escalate risk but will never downgrade a declared or bridge-known risk. It is an advisory defense, not a sandbox.

### 8. Keep the live scene authoritative and store only operation receipts

Pi re-inspects relevant scene and context immediately before meaningful mutations. Each mutation carries the inspected file/session generation and relevant target, mode, and selection preconditions. The bridge validates those preconditions on the main thread immediately before execution and again after any approval delay, rejecting stale work rather than silently retargeting it. File replacement invalidates queued work and inspection cursors. Preconditions are scoped to the operation; they do not require a full scene hash or a second scene model. Artists may edit Blender at any time when no Pi mutation is active.

Accepted mutations have a client-supplied idempotency key bound to the authenticated session and validated request content. Duplicate submissions cannot execute the mutation twice; conflicting content for a retained key is rejected. On disconnect, queued work is cancelled and active work receives a cooperative cancellation signal but may finish before observing it. A bounded outcome ledger survives connection replacement within the bridge lifetime and is accessible only after fresh pairing with appropriate trust. Pi reconciles accepted work rather than automatically resubmitting it. If the bridge restarted, the ledger entry expired, or acceptance cannot be established, Pi reports outcome unknown and requires inspection and an explicit new decision before any retry.

Each completed or failed operation produces a receipt containing identifiers, timestamps, summary, declared and effective risk, trust state, undo outcome, checkpoint reference, bounded logs, artifacts, warnings, duration, result, and structured error details. Receipts must not contain pairing codes, session credentials, or unredacted secrets. Persistence outside Blender is optional and bounded; the initial source of recovery truth is Blender undo plus checkpoint metadata.

A declarative scene twin was rejected because artist edits, mode state, add-on data, simulations, and Blender's full data model would cause rapid divergence.

### 9. Support rich interaction without putting large artifacts in protocol frames

Progress, phase changes, logs, warnings, artifact creation, scene-change hints, completion, and failure are JSON-RPC notifications. Cancellation distinguishes requested by the caller, received by the bridge, and observed by execution. Receiving a request sets a thread/process-safe signal that cooperative scripts and staged bridge operations check; it does not imply that execution has stopped. The UI and protocol will never imply that arbitrary running Python can be safely force-killed.

A cancellation check or progress notification does not yield Blender's event loop. During synchronous non-yielding execution, Blender's panel may not redraw and its cancel/revoke controls may be unavailable; Pi shows only the latest acknowledged state. Workflows advertised as responsive must use bounded stages that return to Blender's event loop or supported asynchronous jobs, with measured responsiveness limits. Tests use finite non-cooperative work and an external watchdog; a watchdog timeout fails the test and may terminate the isolated test process, never masquerading as supported production cancellation.

Supported asynchronous jobs must be registered to an owning operation before launch. Returning from the launching Python call does not complete that operation or release its mutation slot. Completion, receipts, and final artifacts wait for the tracked job's terminal state. Only documented non-mutating status and cancellation operations may proceed while that slot is held. Job adapters define terminal detection, cancellation, failure, and disconnect/file-load cleanup. Arbitrary unregistered asynchronous work is outside managed lifecycle and recovery guarantees and must not be advertised as safely tracked execution.

Images, `.blend` checkpoints, exported models, and large JSON reports are written to a session artifact directory and represented by descriptors containing ID, role, media type, canonical path, size, and SHA-256 digest. Pi validates allowed paths, file type, and size before a bounded read, verifies the digest over the bytes read, and exposes only those same verified bytes to Pi/model content. A later reopen must be revalidated; verification does not authorize consumption of a potentially replaced file. Small structured values remain inline. Large scene inspections use pagination, cursors, or artifacts rather than enormous messages.

### 10. Make artist-visible status part of the safety model

The Blender extension panel shows listener state, paired client identity, trust level, current operation summary and phase, checkpoint status, recent outcome, and controls to deny pairing, revoke trust, request cooperative cancellation, and locate recovery information. Pi commands and tool renderers expose corresponding status and actionable diagnostics.

The bridge must not silently launch, install itself, elevate trust, or persist credentials. Setup may be assisted by Pi only after explicit user approval and must verify the installed bridge version and artifact digest.

### 11. Use focused workflow skills rather than one monolithic manual

The package will provide skills for setup and diagnostics, scene workflows, modeling, materials and nodes, animation and rigging, rendering and visual review, and troubleshooting/recovery. Skills share principles: inspect first, use the data API where practical, account for operator context, make bounded changes, report progress, verify structurally and visually, and stop on unresolved errors.

Skills include only instructions and curated references; executable authority remains in the Pi tools and authenticated bridge. Examples must avoid destructive defaults and clearly distinguish verified Blender 5.2 APIs from assumptions requiring runtime introspection.

### 12. Minimize dependencies and pin the supply chain

The Blender extension will prefer the Python standard library so it can be self-contained and avoid runtime package installation. Pi host packages are peer dependencies as required by Pi packaging rules. Any additional dependency must be justified, verified as the latest applicable release at adoption time, locked with integrity metadata, reviewed for licensing and maintenance, and included in SBOM and vulnerability checks.

GitHub Actions will be pinned to verified immutable commit SHAs, use least-privilege permissions, and separate untrusted pull-request validation from privileged publishing. Releases use protected environments and trusted publishing where available, generate checksums, SBOMs, provenance and attestations, and verify that npm and Blender artifacts derive from the tagged source.

### 13. Test contracts at component and real-Blender levels

Tests will include:

- protocol framing, malformed input, size limits, authentication, schema, and compatibility fixtures;
- pairing expiry, attempt limits, approval, revocation, and secret-redaction tests;
- TypeScript unit tests for tools, lifecycle, truncation, artifact validation, and diagnostics;
- Python unit tests for framing, queues, serialization, receipts, risk escalation, and checkpoint policy;
- Blender 5.2 integration tests for main-thread dispatch, fresh namespaces, undo behavior, file-load lifecycle, viewport capture, artifacts, and representative `bpy` changes;
- cross-language conformance tests using the same protocol fixtures;
- packaging tests that install the produced npm package and Blender extension into isolated locations;
- end-to-end tests pairing Pi's client library with a real Blender process where the CI platform supports it.

Mocks alone are insufficient for thread, undo, context, and compatibility behavior. CI may use a pinned Blender archive whose source URL and SHA-256 are verified before execution.

### 14. Establish repository governance and evidence before claiming maturity

The initial repository includes README, LICENSE, SECURITY, CONTRIBUTING, CODE_OF_CONDUCT, GOVERNANCE, SUPPORT, CHANGELOG, CODEOWNERS, issue forms, pull-request template, Dependabot, CI, release automation, dependency review, static analysis, Scorecard, and `.bestpractices.json`.

`.bestpractices.json` is an evidence-backed automation proposal, not a declaration that the badge is achieved. Unknown or organization-dependent answers remain `?`; controls such as 2FA enforcement, branch rules, review history, response performance, release signing, and bus factor are not claimed without evidence. Repository settings that cannot be encoded in files are tracked as maintainer actions.

The threat model explicitly covers arbitrary Python authority, local pairing limitations, prompt-driven destructive actions, malicious `.blend` files and add-ons, artifact path manipulation, denial of service, protocol abuse, dependency compromise, and release compromise.

## Risks / Trade-offs

- **[Trusted Python can damage or exfiltrate user data]** → Require explicit session trust, display Run Script-equivalent warnings, bind only to loopback, expire credentials, document isolation options, audit operations, and require approval for declared/detected obvious external hazards. These pre-execution checks cannot enforce per-effect mediation or reliably detect all indirect behavior.
- **[A malicious same-user local process may attack pairing or steal process data]** → Use short-lived codes, explicit Blender approval, strong in-memory credentials, rate limits, owner-readable discovery files, and a precise threat model; do not claim protection after OS-account compromise.
- **[Arbitrary Python may freeze Blender and cannot be killed safely]** → Teach bounded staged operations, provide cooperative cancellation and progress, serialize mutations, use Blender jobs where supported, and describe cancellation honestly.
- **[Undo does not cover every mutation or external effect]** → Use a supported undo operator where possible, checkpoint elevated-risk work, block on checkpoint failure, and obtain approval for external effects.
- **[Risk classification can be incomplete]** → Report uncertainty without blanket checkpoint/approval requirements, never let heuristics downgrade declared risk, keep artist-visible summaries, and make recovery independent of classifier perfection.
- **[Protocol or package/bridge version skew]** → Negotiate protocol and capabilities, test compatibility fixtures, fail closed on incompatible majors, and release both components together.
- **[Large scene data or images can exhaust memory and model context]** → Enforce frame/output limits, paginate inspections, transfer large content as verified artifacts, and truncate model-facing results.
- **[Blender UI or file loads may disrupt timers and handlers]** → Use persistent supported handlers where appropriate, integration-test lifecycle transitions, invalidate queued work and cursors on file replacement, re-establish bridge scheduling safely, and expose clear reconnect diagnostics.
- **[Persistent Python I/O threads may be unsupported despite avoiding `bpy`]** → Gate architecture selection on target-version documentation and representative stress tests; retain process-isolated I/O as an alternative, not a late emergency rewrite.
- **[Lost acknowledgements may cause duplicate mutations]** → Use bounded idempotency/outcome records, no automatic mutation retry after ambiguous disconnects, and explicit outcome-unknown handling.
- **[Asynchronous jobs may outlive their launching call]** → Retain operation ownership and the mutation slot until tracked termination; exclude unregistered jobs from managed guarantees.
- **[Artist edits can race with Pi operations]** → Permit one mutation at a time, inspect before changes, validate operation-scoped preconditions at execution and after approval, reject stale work, and avoid a stale shadow model.
- **[Mixed-license packaging can mislabel or omit GPL bridge source]** → Keep the bridge under GPL-3.0-only, the Pi-side code under MIT, ship the bridge source and both notices with bundled artifacts, audit copied code and assets, and validate tarball/license metadata. Marketplace publication remains out of scope.
- **[Comprehensive GitHub ceremony can become performative]** → Tie each workflow and document to an actual control, keep `.bestpractices.json` evidence-based, and avoid unsupported security claims.
- **[Cross-platform support increases installation and CI complexity]** → Use standard-library transport, explicit user paths, reproducible packaging, and a tested support matrix; report unsupported environments clearly.

## Migration Plan

This is a greenfield repository, so migration is staged introduction rather than replacement:

1. Establish repository governance, package manifests, protocol schemas, test harnesses, and secure CI without publishing a functional control path.
2. Add the Blender extension with disabled-by-default listener UI, pairing, diagnostics, and protocol conformance tests.
3. Add the Pi client and package tools, then validate pairing and inspection against Blender 5.2 in isolated environments.
4. Add trusted execution, undo wrapping, receipts, risk policy, checkpoints, progress, cancellation, capture, and artifact verification incrementally behind explicit trust.
5. Add workflow skills and representative end-to-end Blender tasks across modeling, materials, animation, and rendering.
6. Produce release candidates, verify installation from packed npm and Blender artifacts, complete threat-model review, and validate OpenSSF/Scorecard evidence.
7. Publish npm and GitHub releases from the same signed tag only after all required checks pass; confirm pi.dev discovery from the published manifest.

Rollback consists of revoking the Blender session, disabling or uninstalling the Blender extension, removing the Pi package, and restoring a recorded checkpoint or ordinary Blender undo state. Releases must document protocol compatibility and provide prior verified artifacts where a previous release exists so users can downgrade both components together. First-release rollback tests use a verified prior release candidate or document the absence of a prior pair and validate uninstall/recovery instead.

Archive this implementation change after pre-publication acceptance and before the final signed commit and pull request. Track publication approval and public-artifact verification in a separate release checklist; archiving does not assert that publication or post-publication checks have already occurred.

## Open Questions

- Which Blender-supported copy/save mechanism provides the least disruptive checkpoint while preserving the artist's active file identity across all supported workflows?
- What checkpoint retention defaults balance disk usage with recovery value, and where should artists configure them?
- Which obvious destructive patterns warrant advisory escalation without excessive false positives, and how should their limitations be tested?
- Which scene-change notifications are reliable enough in Blender 5.2 to emit without expensive whole-scene diffing?
- Should inspection-only access require completed pairing in the first release, or may an explicitly enabled bridge expose a minimal unauthenticated status response?
- Which operating systems are mandatory for the first stable release, and can real Blender integration tests run reliably on each hosted CI environment?
- Are any third-party assets later introduced, and what exact redistribution/attribution terms apply to each? No asset is currently bundled.
