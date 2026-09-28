## Why

Blender artists spend substantial time on repetitive scene construction, inspection, repair, and iteration that can be delegated without replacing their creative judgment. A Pi-native package controlling the artist's open Blender 5.2+ session can remove that toil while preserving direct artist control, Blender's native workflows, and visible recovery paths.

## What Changes

- Scaffold one repository with MIT-licensed Pi-side code and a thin GPL-3.0-only Blender extension, plus shared protocol contracts, skills, tests, documentation, and release automation.
- Add a Pi-native extension with tools for pairing, status, inspection, trusted Blender Python execution, progress, cancellation, visual capture, artifacts, and recovery; no MCP server is introduced.
- Add a small Blender extension that exposes an authenticated loopback bridge, queues requests safely, and dispatches Blender work on the main thread.
- Define a versioned, bidirectional JSON-RPC protocol over framed loopback TCP with capability negotiation, structured results and errors, progress notifications, cooperative cancellation, and artifact descriptors.
- Require short-lived, physical-presence pairing and explicit approval in Blender before issuing an in-memory session credential.
- Permit broad, Run Script-equivalent Python and `bpy` access so Pi can support modeling, geometry nodes, sculpting, texturing, shading, rigging, animation, simulation, rendering, import/export, and installed add-ons.
- Keep the live `.blend` as the sole scene authority; wrap supported mutations in ordinary Blender undo and create checkpoints before declared or detected high-risk scene operations.
- Add modular Blender workflow skills that direct Pi to inspect current state, execute bounded changes, report progress, verify visually, and recover safely.
- Add normal open-source repository governance and security material, including README, license, contribution and conduct policies, security and support policies, governance, changelog, issue and pull-request templates, CODEOWNERS, Dependabot, pinned least-privilege CI, release provenance, SBOMs, Scorecard, and a truthful `.bestpractices.json` proposal for OpenSSF Best Practices.
- Explicitly exclude MCP compatibility, a constrained one-tool-per-operation Blender API, a declarative shadow scene model, pre-5.2 Blender support, cloud relays, and official Blender Extensions marketplace publication from the initial change.

## Capabilities

### New Capabilities
- `repository-foundation`: Repository structure, governance, security documentation, GitHub automation, supply-chain controls, and OpenSSF Best Practices evidence.
- `pi-package-distribution`: Pi package manifest, native extension and skill discovery, installation guidance, bundled bridge assets, and npm/pi.dev release behavior.
- `session-pairing`: Physical-presence pairing, explicit Blender approval, ephemeral session credentials, trust states, and session revocation.
- `blender-bridge-protocol`: Versioned framed JSON-RPC transport, capability negotiation, message validation, concurrency, errors, notifications, and compatibility behavior.
- `blender-code-execution`: Broad Blender Python execution, fresh namespaces, main-thread dispatch, structured values, progress, logging, and cooperative cancellation.
- `blender-recovery`: Risk declarations, undo integration, operation receipts, checkpoint policy, and recovery behavior for destructive or external effects.
- `blender-observability`: Scene inspection, viewport and render evidence, artifact handling, bounded output, diagnostics, and artist-visible operation status.
- `blender-workflow-skills`: Skills covering setup, scene work, modeling, materials and nodes, animation, rendering, verification, and troubleshooting.

### Modified Capabilities

None.

## Impact

- Introduces TypeScript code running within Pi and Python code running within Blender with the user's operating-system permissions.
- Adds a local authenticated protocol and a Blender extension that must remain responsive within Blender's main-thread constraints.
- Adds npm and GitHub release artifacts, including the bundled Blender extension, protocol schemas, checksums, attestations, provenance, and SBOMs.
- Establishes Blender 5.2+ as the compatibility floor and Pi's package system as the only initial agent integration.
- Requires security documentation to state clearly that full trust grants Run Script-equivalent authority and is not a sandbox.
- Bundles GPL-3.0-only Blender bridge source with the MIT-licensed Pi package in GitHub/npm artifacts, with separate license notices and source availability; official `extensions.blender.org` publication remains out of scope.
