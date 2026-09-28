# blender-pi

Artist-led automation for a **live Blender 5.2+ session** from [Pi](https://pi.dev). The artist chooses the work, pairs locally, reviews sensitive operations in Blender, and keeps the open `.blend` as the source of truth. Pi is intended to inspect the current scene, perform bounded changes with trusted Python, report results, and help the artist verify or recover. This is an **early implementation scaffold**, not a working or published Blender control package yet.

> **Security:** Full-trust access is equivalent to Blender **Run Script**. Generated Python is **not sandboxed** and can read/write files, access Blender's resources and add-ons, invoke processes, and use network libraries under your user account. Planned pairing, approvals, undo and checkpoints do not make arbitrary code safe or reverse external effects. Do not install or grant trust until you understand the risks; use a disposable project for testing.

## Intended workflow and architecture

1. The artist explicitly starts a disabled-by-default Blender extension, then reviews a short-lived pairing request in Blender. Even scene inspection requires approved pairing.
2. Pi discovers a literal-loopback bridge, inspects the **current** Blender scene, and proposes a small change with a summary, expected effects, risk and preconditions.
3. Blender validates trust and preconditions on its main thread, requires approval for declared/detected external effects and uncertain effects, and saves a checkpoint before high-risk or unknown work.
4. Pi reports progress, structured results, visual evidence, actual undo/checkpoint availability and errors. The artist reviews the outcome and remains in control.

The planned Pi-native TypeScript extension lives in `extensions/`; a thin Blender-side Python add-on belongs in `bridge/`; `protocol/` holds language-neutral wire contracts and `skills/` will hold domain guidance. A separate Python I/O process handles local sockets; all `bpy` access remains on Blender's main thread. No MCP server, cloud relay or shadow scene model is planned. **The Pi entry point remains inert. Blender's opt-in, process-isolated listener supports only a bounded public handshake and rejects pairing and privileged control; no authenticated connection, scene inspection or trusted execution is implemented.**

## Installation status and support

**Do not use `pi install` expecting Blender control yet.** `@scetrov/blender-pi` is a planned npm/pi.dev package, not a published functional release. When ready, supported distribution channels will be **npm/pi.dev** for Pi plus a bundled Blender extension, and **GitHub Releases** for verified artifacts. The official Blender Extensions marketplace is out of scope. The initial target is Blender **5.2 or newer**, Linux x64 and Windows x64; real cross-platform integration tests are still pending. Other platforms are unsupported pending validation. See [compatibility](docs/compatibility.md) and [licensing](docs/licensing.md): Pi-side material is MIT; the Blender extension will be GPL-3.0-only.

For development, clone the repository and run `npm ci --ignore-scripts`, then `npm run validate`. These commands validate the current scaffold only; they do not install Blender or connect Pi. Prototype Blender tests require a separately obtained verified 5.2 binary and an isolated test directory. Run `python3 scripts/stage_bridge.py` before testing the Blender add-on; this creates an ignored `dist/bridge/` copy containing both GPL bridge code and MIT wire sources. `/blender-setup` verifies the bundled extension against release metadata and copies it into Blender's 5.2 user extensions directory only after interactive approval. Print mode explains the change and does not install. Setup does not enable the extension, launch Blender, or change trust. Loading the Pi package still does not modify Blender.

## Design and project status

- [Architecture](docs/architecture.md) and [I/O feasibility](docs/io-architecture.md)
- [Wire protocol decisions](docs/protocol.md)
- [Pairing](docs/pairing.md) and [local threat model](docs/threat-model.md)
- [Risk and approval policy](docs/risk-policy.md)
- [Checkpoint prototype and recovery limits](docs/recovery.md)
- [Support matrix](docs/compatibility.md)
- [Dependency provenance](docs/dependencies.md) and [update review](docs/dependency-updates.md)
- [Licensing and bundled materials](docs/licensing.md)
- [Privacy](docs/privacy.md), [release process](docs/release-process.md), and [repository settings](docs/repository-settings.md)
- [OpenSpec change and task progress](openspec/changes/establish-blender-pi-package/tasks.md)

See [security reporting](SECURITY.md), [contributing](CONTRIBUTING.md), [governance](GOVERNANCE.md), [conduct](CODE_OF_CONDUCT.md), [support](SUPPORT.md), and [changelog](CHANGELOG.md). Release procedures and repository controls are still being established. Project code does not currently send telemetry to a project-operated service. Future network effects by trusted scripts or third-party add-ons are not covered by that statement.
