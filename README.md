# blender-pi

Artist-led automation for a **live Blender 5.2+ session** from [Pi](https://pi.dev). The artist directs work, explicitly starts the local bridge, approves pairing in Blender, and keeps the open `.blend` authoritative. Pi can inspect, execute trusted Blender Python, report progress, capture evidence, and assist recovery. **Pre-release: not published or qualified for production.** Current cross-platform CI has [two failing checks](docs/security-validation.md); do not treat a passing local test as release approval.

> **Security:** Full trust is Blender **Run Script-equivalent**, not a sandbox. Scripts and installed add-ons can read or change files, use the network, run processes and access resources available to Blender. Approval heuristics can miss indirect effects, and Blender undo/checkpoints do not reverse external effects. Pair only a client you recognize, review its proposed effects, and test on copies of valuable scenes.

## What it does

- Blender's explicitly started GPL-3.0-only extension owns loopback discovery, physical-presence pairing, main-thread `bpy` dispatch, operation gating, undo/checkpoints, live inspection and artifacts. Socket I/O runs in a separate process without `bpy`.
- The MIT Pi extension exposes tools, commands and workflow skills. Pairing is required even for scene inspection; full trust is required for arbitrary Python and recovery actions. Pi and Blender use a versioned, bounded, framed JSON-RPC protocol, not MCP or a cloud relay.
- Changes use operation-scoped live-state preconditions and bounded receipts. High-risk scene work needs a verified checkpoint; declared/detected destructive external effects need explicit artist approval. Cancellation is cooperative and may be delayed by non-yielding work. Lost mutation outcomes require re-pairing and reconciliation, **not automatic retry**.

## Development installation (not a published release)

See [installation and setup](docs/installation.md) for offline build, explicit install, pairing, uninstall and platform limitations. Use Node.js >=22.19, the operator-approved pnpm 12.6.0 and the committed lockfile; install development dependencies with `pnpm install --frozen-lockfile --ignore-scripts`. Do **not** use `npm install` or `npm ci` in this repository. Run `npm run validate`, then `npm run release:build` for locally built Blender ZIP and npm tarball in ignored `dist/release/`. These commands do not publish, enable the bridge, or grant trust. Blender 5.2.2 real tests use verified official archives and isolated user configurations; GUI-only behavior needs separate validation.

The target distribution is **npm/pi.dev and GitHub Releases** after release acceptance, on Linux x64 and Windows x64 with Blender 5.2+. macOS and ARM platforms are not supported for this first release. The official Blender Extensions marketplace and MCP compatibility are out of scope. Pi-side code, skills and docs are MIT; the Blender bridge is GPL-3.0-only with bundled source and notices. See [compatibility](docs/compatibility.md) and [licensing](docs/licensing.md).

## Documentation

- [Setup and diagnostics](docs/installation.md) · [Secure use](docs/secure-use.md) · [Architecture](docs/architecture.md)
- [Protocol](docs/protocol.md) · [Pairing](docs/pairing.md) · [Risk policy](docs/risk-policy.md) · [Recovery](docs/recovery.md)
- [Threat model](docs/threat-model.md) · [Privacy](docs/privacy.md) · [Compatibility](docs/compatibility.md)
- [Release process](docs/release-process.md) · [Separate release checklist](docs/release-checklist.md) · [Security validation](docs/security-validation.md)
- [Dependency review](docs/dependencies.md) · [Contributing](CONTRIBUTING.md) · [Security reporting](SECURITY.md) · [Support](SUPPORT.md)
- [Governance](GOVERNANCE.md) · [Code of conduct](CODE_OF_CONDUCT.md) · [Changelog](CHANGELOG.md) · [OpenSpec progress](openspec/changes/establish-blender-pi-package/tasks.md)

There is no project-operated telemetry service. Pi and any chosen model provider have separate data-handling terms; trusted scripts may make their own external connections. See [privacy](docs/privacy.md).
