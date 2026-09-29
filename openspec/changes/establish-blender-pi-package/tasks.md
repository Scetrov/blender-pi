## 1. Resolve Release-Blocking Design Questions

- [x] 1.1 Document the first-release operating-system support matrix and the CI environments that can run real Blender 5.2 integration tests.
- [x] 1.2 Document GPL-3.0-only licensing for the thin Blender extension and MIT licensing for Pi-side code, record third-party constraints and packaging obligations, and confirm official marketplace publication remains excluded.
- [x] 1.3 Prototype Blender 5.2 checkpoint techniques and document the selected mechanism, active-file behavior, failure modes, storage location, and retention defaults; test unsaved files, relative asset paths, and external caches, and state which external files recovery does not restore.
- [x] 1.4 Define the initial risk taxonomy and pre-execution approval rules: require checkpoints for declared/detected high-risk scene effects, approve declared/clearly detected destructive external hazards, and state that unrestricted Python prevents enforceable per-effect mediation.
- [x] 1.5 Decide whether inspection-only access requires completed pairing and record the decision in the threat model and protocol contract.
- [x] 1.6 Verify the latest applicable released versions, licenses, provenance, and integrity information for every proposed development or runtime dependency before adding manifests.
- [x] 1.7 Gate I/O architecture selection on Blender 5.2 threading documentation and feasibility tests combining networking with Cycles, Python drivers, file loads, and shutdown; do not equate avoiding `bpy` or passing a short stress test with support. Select process-isolated I/O or another documented mechanism if supportable in-process I/O cannot be established, and record lifecycle/GIL/responsiveness limits before section 4 implementation.

## 2. Scaffold the Repository and Governance

- [x] 2.1 Create the `extensions`, `skills`, `bridge`, `protocol`, `tests`, `docs`, and supporting configuration directory structure described by the design.
- [x] 2.2 Create the npm package manifest with the `pi-package` keyword, explicit Pi resource paths, files allowlist, supported engines, scripts, repository metadata, MIT license, and Pi host peer dependencies.
- [x] 2.3 Generate and commit the selected package-manager lockfile with integrity metadata, and add deterministic formatting, linting, type-checking, test, package, and validation scripts.
- [x] 2.4 Add `README.md` covering purpose, artist-led workflow, architecture summary, Blender 5.2 minimum, installation status, security warning, supported distribution channels, and project maturity.
- [x] 2.5 Add root MIT `LICENSE` plus a GPL-3.0-only `bridge/LICENSE` and explicit scope/packaging notices; add `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `GOVERNANCE.md`, `SUPPORT.md`, and `CHANGELOG.md` with truthful current policies and private vulnerability-reporting guidance.
- [x] 2.6 Add `.gitignore`, `.editorconfig`, formatting, linting, type-checking, Python validation, spelling, and pre-commit configuration without introducing generated-file churn.
- [x] 2.7 Add CODEOWNERS, issue forms, issue configuration, pull-request template, release template, and repository-setting documentation for rulesets, required reviews, signed commits, 2FA, secret scanning, and private vulnerability reporting.
- [x] 2.8 Add Dependabot configuration for every supported package ecosystem and GitHub Actions with bounded update frequency and reviewer guidance.
- [x] 2.9 Add a root `.bestpractices.json` containing only evidence-backed proposals and `?` for unsupported, organizational, historical, or repository-setting claims; validate it against the official schema tooling.
- [x] 2.10 Add architecture, threat-model, protocol, pairing, recovery, compatibility, privacy, and release-process documentation skeletons linked from the README.

## 3. Define and Test the Shared Protocol Contract

- [x] 3.1 Define the initial protocol versioning policy, method namespace, stable error codes, trust states, operation states, risk levels, artifact roles, and compatibility rules, including stale preconditions, idempotency conflicts, outcome unknown, and requested/received/observed cancellation states.
- [x] 3.2 Create language-neutral JSON schemas for JSON-RPC envelopes, handshake and capabilities, pairing, inspection, execution, progress, logs, warnings, artifacts, cancellation, receipts, checkpoints, diagnostics, and structured errors; include file/session generations, operation-scoped preconditions, idempotency keys, outcome lookup, and tracked job identity.
- [x] 3.3 Create accepted and rejected framing fixtures covering partial reads, combined frames, UTF-8, empty payloads, malformed lengths, oversized frames, invalid JSON, and invalid JSON-RPC envelopes.
- [x] 3.4 Create accepted and rejected schema fixtures covering required fields, bounds, unknown fields, version negotiation, redaction, and each stable error outcome.
- [x] 3.5 Implement the TypeScript four-byte big-endian frame encoder and incremental decoder with bounded allocation and unit tests.
- [x] 3.6 Implement the Python four-byte big-endian frame encoder and incremental decoder using the standard library with equivalent unit tests.
- [x] 3.7 Implement TypeScript and Python schema validation for pre-dispatch messages without adding an unjustified Blender runtime dependency.
- [x] 3.8 Add cross-language conformance tests that run the same fixtures against TypeScript and Python and fail on behavioral divergence.
- [x] 3.9 Document the wire protocol, lifecycle diagrams, frame limits, capability negotiation, method schemas, ordering guarantees, and compatibility policy.

## 4. Build the Blender Extension Foundation

- [x] 4.1 Create a Blender 5.2 extension manifest and Python package with registration, unregistration, preferences, properties, and a 3D View sidebar panel.
- [x] 4.2 Implement an idempotent bridge lifecycle that starts only by explicit artist action, binds an ephemeral literal-loopback socket, and releases sockets, owned I/O threads/processes, timers, handlers, queues, and sensitive state on stop or unload.
- [x] 4.3a Implement process-isolated connection acceptance, framed-message parsing, bounded responses and connection cleanup without `bpy`; expose only the public handshake/pairing transport and reject privileged methods until authentication exists.
- [x] 4.4 Implement bounded thread/process-safe inbound and outbound queues plus a Blender-supported main-thread dispatcher; deliver cancellation signals independently of the main-thread work queue.
## 5. Implement Pairing and Trust

- [x] 5.1 Implement owner-readable user-scoped discovery descriptors containing endpoint and bridge identity but no session credential, including atomic replacement and stale-descriptor cleanup.
- [x] 5.2 Implement cryptographically random pending pairing IDs and human-enterable codes with expiry, single use, strict attempt limits, rate limits, and log exclusion.
- [x] 5.3 Implement Pi pairing requests carrying client name, package version, working directory, requested trust, and expiry.
- [x] 5.4 Implement Blender-side pairing approval and denial UI that clearly displays requester identity and Run Script-equivalent warnings for full trust.
- [x] 5.5 Implement cryptographically random in-memory session credentials, authenticated request binding, credential replacement, explicit revocation, bridge-stop invalidation, and constant-time credential comparison where applicable.
- [x] 5.6 Implement distinct unpaired, pending, inspection, and full-trust states and enforce method authorization before main-thread scheduling.

## 4. Complete authenticated Blender bridge integration (after pairing)

- [x] 4.3b Complete authenticated request gating and response writing through the process-isolated I/O component, including credential binding, authorization before queueing and bounded cleanup; no `bpy` in the child.
- [x] 4.8 Add bounded local diagnostics for listener, selected I/O component, queue, dispatcher, protocol, and recent-error state with credential redaction.

## 5. Complete Pairing and Trust

- [x] 5.7 Add tests for successful pairing, denial, dismissal, expiry, replay, guessing limits, restart, revocation, concurrent pairing, stale discovery, and secret redaction.
- [x] 5.8 Complete the pairing and local-adversary threat-model documentation, explicitly describing what same-user compromise is outside the security boundary.

## 8. Establish inspection precondition foundation (before execution)

- [x] 8.1a Implement bridge-owned main-thread inspection of file/session generations and operation-relevant active target, mode, and selection under inspection trust; expose these values to clients for execution preconditions. Keep larger scene inspection in 8.1b.

## 6. Implement Trusted Blender Code Execution

- [x] 6.1 Implement validated execution requests containing summary, declared risk, expected effects, undo preference, checkpoint policy, source code, idempotency key, and inspected file/session generation with relevant target/mode/selection preconditions; revalidate preconditions on the main thread immediately before execution and after approval delays.
- [x] 6.2 Implement a bridge-owned Blender operator with `REGISTER` and `UNDO` that produces meaningful Pi-labeled undo entries for supported mutations. Integrate 6.1 execution-time revalidation at this boundary before marking either task complete.
- [x] 6.3 Implement fresh per-operation execution namespaces containing documented Blender bindings and no implicit persistence of Python locals or cached datablock references.
- [x] 6.4 Implement the injected bridge interaction API for structured results, bounded logs, warnings, progress, artifact registration, and cooperative cancellation checks.
- [x] 6.5 Implement stdout and stderr capture with byte and line limits, truncation metadata, secret redaction, and restoration after success or failure.
- [x] 6.6 Implement deterministic JSON result serialization for primitive values, finite numbers, arrays, objects, supported `mathutils` values, and Blender datablock references.
- [x] 6.7 Reject cycles, excessive depth, non-finite numbers, oversized values, and unsupported Python objects with stable serialization errors.
- [x] 6.8 Implement compile, runtime, cancellation, serialization, bridge, and internal failure outcomes with bounded safe tracebacks and correlation IDs.
- [x] 6.9a Implement and test the internal queued, active, cancellation-requested, completed, failed, and cancelled operation state machine, with bounded ordered progress/completion events and distinct caller-requested, bridge-received, and execution-observed cancellation. Do not claim wire delivery yet.

## 4. Complete mutation lifecycle (after execution foundations)

- [x] 4.5a Implement and test a bounded in-memory idempotency/outcome ledger binding keys to authenticated session identity and validated request content; reject duplicate/conflicting submissions, retain terminal outcomes across connection replacement, and expire safely. No mutation transport or reconciliation is claimed yet.
- [x] 4.6 Implement bridge identity, Blender/package/protocol version reporting, capability negotiation, mandatory-capability checks, and incompatible-version diagnostics.
- [x] 4.7a Implement and verify file-load and extension-reload lifecycle handling for the current bridge: invalidate old-session queued work, revoke stale authentication and callbacks, and avoid duplicated dispatchers. Do not claim cursor or tracked-job cleanup before those features exist.

## 6. Verify Blender execution and long-running jobs

- [x] 6.10 Add Blender integration tests proving that all `bpy` access occurs on the main thread, namespaces are fresh, representative modeling and shading code executes, and undo behavior matches documentation.
- [x] 6.11a Add real-Blender tests for internal cooperative cancellation, finite non-cooperative/native work and stale UI. Use an external watchdog whose timeout fails the test and may terminate only the isolated test process; never present watchdog termination as supported production cancellation.
- [x] 6.13a Build and test internal main-thread ownership for a supported Blender asynchronous render: register before launch, retain the mutation slot until terminal detection, and define cancellation, failure, disconnect and file-load behavior. Do not claim final receipts or wire exposure yet.
- [x] 6.12 Implement bounded stages that return to Blender's event loop for workflows advertised as responsive, and measure their responsiveness limits.

## 7. Implement Risk, Checkpoints, and Recovery

- [x] 7.1 Implement request validation for summaries, expected effects, risk, undo, checkpoint policy, and external-effect declarations.
- [x] 7.2 Implement effective-risk calculation that preserves or escalates declared risk, flags clearly detected hazards without classifying all arbitrary Python as unknown, and never uses absence of a heuristic match to claim code is safe.
- [x] 7.4 Implement collision-resistant checkpoint naming, source-scene metadata, configurable retention, safe cleanup, and failure behavior that blocks elevated-risk execution.
- [x] 7.3 Implement verified pre-execution checkpoints for declared or clearly detected high-risk scene operations using the selected Blender 5.2 mechanism.
- [x] 7.5 Implement explicit Blender-side approval for declared or clearly detected destructive external effects (file overwrite/broad deletion, process launch, network disclosure, installation change); show uncertain targets honestly, test denial before execution and avoid blanket approval prompts for ordinary full-trust Blender code.

## 6. Complete operation notifications (after mutation lifecycle and risk gating)

- [x] 4.5b1 Implement a persistent bounded single-controller transport foundation with authenticated reconnect/disconnect cleanup and independent cancellation signal delivery. Continue refusing remote mutation; retain the ledger across connection replacement.
- [x] 4.5b2 Implement risk-gated single-mutation wire admission/settlement: cancel queued work on disconnect, cooperatively signal active work, retain bounded outcomes across connection replacement, and reconcile only after fresh full-trust pairing with both operation ID and idempotency key. Do not enable mutation transport until 7.1–7.5 controls are active.
- [x] 7.6 Implement bounded operation receipts containing risk, trust, outcome, timing, undo, checkpoint, warnings, artifacts, truncation, errors, and redacted correlation data. Complete before 6.9b so completion notifications satisfy the receipt schema.
- [x] 6.9b Integrate authenticated bidirectional ordered operation progress/completion notifications and asynchronous cancellation delivery over the persistent controller connection. Test requested-by-caller vs received-by-bridge vs observed-by-execution, including blocked native work and disconnects; do not expose execution before 7.1–7.5 controls are active.
- [x] 6.11b Add real-Blender integration tests for delayed wire acknowledgement during finite native work and disconnect; distinguish caller intent from bridge receipt and execution observation. Use an external test-process watchdog, never production force cancellation.
- [x] 6.13b Integrate tracked asynchronous jobs with deferred final receipts and artifacts and risk-gated wire operation ownership; test no early completion or overlap and cleanup across disconnect/file load. Document unregistered asynchronous work as outside managed guarantees.
- [x] 7.7 Implement artist-confirmed checkpoint restore with unsaved-change warnings, source validation, result recording, and no automatic deletion of the source checkpoint.
- [x] 7.8 Add integration tests for low, moderate, high, declared/detected external-effect, and unknown operations; checkpoint failure; partial mutation failure; undo; restore; retention; and secret redaction. Prove that ordinary full-trust code needs no blanket uncertainty approval, partial failures remain failed even when undo requires `FINISHED`, and advisory approvals do not claim per-effect enforcement.
- [x] 7.9 Complete artist-facing recovery documentation for ordinary undo, failed operations, checkpoints, restore, and unrecoverable external effects.

## 8. Implement Inspection, Evidence, and Artifacts

- [x] 8.1b Complete bridge-owned inspection for Blender and file state, active scene, current mode, selection, objects, collections, materials, cameras, render settings, and bridge diagnostics under inspection trust (building on 8.1a).
- [x] 8.2 Add pagination, cursors, summaries, and structured-report artifacts so large scenes cannot create unbounded protocol or model-context results.
- [x] 4.7b After 6.13 and 8.2, invalidate inspection cursors and safely clean up tracked jobs on file replacement/reload; test their terminal/interrupted outcomes and stale callbacks.
- [x] 8.3 Implement supported viewport, workbench, and rendered evidence capture with scene, view, camera, frame, engine, dimensions, and timestamp metadata.
- [x] 8.4 Implement per-session artifact directories and descriptors containing opaque ID, role, media type, canonical path, byte size, and SHA-256 digest.
- [x] 8.5 Implement Pi-side artifact validation: check allowed paths, existence, type, and size before bounded reading, then verify the digest before exposing content to Pi/model attachments. Consume the same verified bytes and test replacement between verification and consumption; any reopen requires fresh validation.
- [x] 8.6 Implement artifact lifecycle and bounded cleanup that preserves checkpoints according to recovery policy and never deletes arbitrary user files.
- [x] 8.7 Implement Blender panel status for listener, pairing, client identity, trust, operation summary, effective risk, phase, progress, checkpoint, recent outcome, revoke, cancellation, and recovery location.
- [x] 8.8 Add tests for current-state inspection after manual artist edits, unavailable capture context, image attachment, large reports, path traversal, symlink escape, digest mismatch, size limits, and cleanup boundaries.
- [x] 8.9 Verify through network-observation tests that project code sends no undisclosed telemetry, prompts, scene data, receipts, code, or artifacts to a project-operated remote service.

## 9. Build the Pi-Native Extension and Package UX

- [x] 9.1 Implement Pi session lifecycle management that discovers bridges on demand, maintains one authenticated connection, handles reconnects, and cleans up idempotently on session shutdown or reload. Re-pair and reconcile retained mutation outcomes without automatic resubmission; surface outcome unknown and require inspection plus an explicit new decision when reconciliation is impossible.
- [x] 9.2 Register compact Pi tools for bridge status, pairing, inspection, trusted execution, capture, job status, cooperative cancellation, checkpoint listing, and restore.
- [x] 9.3 Define strict TypeBox parameters, concise model-facing descriptions, prompt guidance, and structured details for every Pi tool.
- [x] 9.4 Implement Pi commands for setup, pairing, diagnostics, trust status, and bridge-version checks with UI fallbacks for non-interactive Pi modes.
- [x] 9.5 Implement tool-call and result renderers that show operation summary, risk, trust, progress, artifacts, undo, checkpoint, and actionable failure information without hiding raw model-relevant results.
- [x] 9.6 Implement model-facing output truncation and temporary full-output storage using Pi utilities while preventing credential or secret disclosure.
- [x] 9.7 Implement setup that locates the bundled Blender extension, verifies release metadata and digest, explains changes, requests approval, and installs or provides manual installation instructions without silent modification.
- [x] 9.8 Implement package/bridge/protocol compatibility checks and precise diagnostics for absent, disabled, stale, unpaired, unauthorized, incompatible, or unreachable bridges.
- [x] 9.9 Add isolated Pi extension tests for registration, lifecycle, schemas, rendering, setup consent, truncation, artifact validation, compatibility, and all error paths.
- [x] 9.10 Pack and install the npm tarball into an isolated Pi environment and verify extension loading, skill discovery, files allowlist, peer dependency behavior, and absence of undeclared dependencies.

## 10. Author Blender Workflow Skills

- [x] 10.1 Create a setup and diagnostics skill covering installation, Blender enablement, pairing, trust, status, compatibility, and troubleshooting.
- [x] 10.2 Create a scene workflow skill covering live-state inspection, organization, selection, modes, context-sensitive operators, bounded mutations, and receipts.
- [x] 10.3 Create a modeling skill covering meshes, curves, modifiers, geometry nodes, sculpting/remeshing, topology risk, progress, undo, and checkpoints.
- [x] 10.4 Create a materials and nodes skill covering textures, UVs, shaders, node trees, worlds, compositing, asset paths, and visual verification.
- [x] 10.5 Create an animation and rigging skill covering keyframes, actions, drivers, constraints, armatures, simulation staging, baking risk, and cancellation boundaries.
- [x] 10.6 Create a rendering and visual-review skill covering cameras, lighting, render engines, viewport/workbench/final evidence, artifacts, and iterative artist review.
- [x] 10.7 Create a troubleshooting and recovery skill covering runtime introspection, authoritative Blender 5.2 documentation, undo, checkpoints, restore, stale references, context failures, and safe stopping.
- [x] 10.8 Add curated references and non-destructive examples for each skill without maintainer-specific absolute paths or unverified Blender API claims.
- [x] 10.9 Validate skill frontmatter, names, routing descriptions, relative links, packaged discovery, example syntax, and supported Blender APIs in CI.

## 11. Complete Cross-Platform and End-to-End Validation

- [x] 11.1 Create a reproducible Blender 5.2 test acquisition process using official archives, verified SHA-256 values, isolated user configuration, and no reliance on mutable image tags.
- [x] 11.2 Add unit and integration test jobs for each supported operating system and document justified gaps where hosted CI cannot exercise GUI capture.
- [x] 11.2a Deliver validated, bounded, ordered bridge notifications through the Pi transport and session to agent-facing progress/completion; test malformed, oversized, unauthenticated, disconnected, and out-of-order events without leaking credentials.
- [x] 11.2b Implement authenticated main-thread checkpoint listing and artist-confirmed restore over the bridge, with current-scene preconditions, source/unsaved-work warnings, verified owned checkpoints, bounded results, and failure/reload tests. Do not treat a restore request as completed restoration.
- [x] 11.3 Add headless Pi-to-Blender end-to-end tests for startup, discovery, pairing, inspection, full trust, code execution, progress, workbench capture, artifact verification, undo receipt, checkpoint, artist-confirmed restore, revocation, and shutdown. Record that interactive undo and physical viewport capture require a GUI-capable validation environment before release.
- [x] 11.4 Add adversarial protocol tests for malformed frames, oversized payloads, invalid schemas, replay, unauthorized methods, queue flooding, disconnects, path manipulation, and redaction failures. Cover disconnect after mutation but before acknowledgement, conflicting/duplicate idempotency keys, ledger expiry/restart, artist edits during approval, and file replacement with queued work.
- [x] 11.5 Add representative artist-workflow tests spanning object generation, geometry nodes, materials and shading, animation, and rendering against Blender 5.2.
- [x] 11.6 Add performance and responsiveness checks for idle polling, message framing, large-scene inspection, queue processing, progress volume, and artifact limits.
- [ ] 11.7 Run static analysis, CodeQL where applicable, dependency review, vulnerability scanning, secret scanning, license checks, Scorecard, package audit, and Blender extension validation; resolve or explicitly document all findings.
- [x] 11.8 Verify that the working tree remains reproducible after full validation and that generated artifacts are either ignored or produced only in documented output directories.

## 12. Prepare and Verify the Initial Release

- [x] 12.1 Implement reproducible Blender extension packaging and npm packaging with explicit file allowlists and no runtime dependency downloads.
- [ ] 12.2 Implement release automation using immutable actions, least-privilege permissions, protected environments, trusted npm publishing, and no long-lived publish secret where supported.
- [ ] 12.3 Generate checksums, SPDX or CycloneDX SBOMs, build provenance, artifact attestations, and compatibility metadata for npm and Blender artifacts from the same signed version tag.
- [x] 12.4 Verify installation and uninstallation from produced release artifacts on every supported operating system, including rollback to the previous compatible package/bridge pair when one exists. For the first release, use a verified prior release candidate or document the absence of a prior pair and validate uninstall/recovery instead.
- [x] 12.5 Complete README, installation, secure-use, privacy, threat-model, architecture, protocol, pairing, recovery, compatibility, contribution, and release documentation from tested behavior.
- [x] 12.6 Perform a truthful OpenSSF Best Practices assessment, validate `.bestpractices.json`, run OpenSSF Scorecard as supporting evidence, and record repository-setting or human-attestation follow-ups without overstating status.
- [x] 12.7 Review the complete change against every OpenSpec scenario and record test or evidence coverage for each requirement.
- [x] 12.8 Run configured pre-commit checks explicitly, install the hook with `pre-commit install` if it is not active, and resolve all repository validation failures.
- [x] 12.9 Prepare a separate release checklist requiring signed release approval before publication and subsequent verification of npm installation, pi.dev gallery discovery, GitHub artifact integrity, provenance, SBOMs, checksums, and documented compatibility from public artifacts; publication and post-publication verification are not implementation-archive prerequisites.
- [ ] 12.10 Archive the completed implementation change after pre-publication acceptance and before the final signed conventional commit and pull request, preserving Agent and Model attribution trailers within repository line-length limits. Do not claim the separate release checklist is completed merely because this change is archived.
