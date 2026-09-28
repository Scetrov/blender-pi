# Handoff — Blender Pi OpenSpec implementation

**Stop point (updated):** Active change `establish-blender-pi-package` (`spec-driven`), **108/120 complete**. Next pending task: **11.7**. On resume announce `Using change: establish-blender-pi-package` and how to override (`/opsx-apply <other>`). Then run:

```bash
openspec status --change establish-blender-pi-package --json
openspec instructions apply --change establish-blender-pi-package --json
```

Read every returned `contextFiles` path. `openspec/changes/establish-blender-pi-package/tasks.md` is authoritative. Do not discard the untracked or modified tree. No commit, pull request, or archive has occurred. The branch is `main`.

## Resume rules

- Follow `AGENTS.md` and the repository `AGENTS.md`. Short build and test commands run in the `bubblewrap-isolation` sandbox. The project root is the only writable host mount. Do not mount home, the pnpm store, credentials, or a display socket, and do not enable sandbox network.
- Standing read-only mounts, when a command needs them, are Node `/home/scetrov/.nvm/versions/node/v24.21.0` and Blender `/home/scetrov/software/blender-5.2.2-linux-x64`. The standard launcher has no extra-mount flag, so copy its `bwrap` arguments and add only an approved `--ro-bind`. System `/usr/bin/node` is v20 and cannot run `node --experimental-strip-types`.
- Pi 0.87.1 CLI verification, already done for 9.10, needed one additional read-only mount: `/home/scetrov/.bun/install/global/node_modules`. That mount was approved for that check. Do not treat it as a standing mount, and do not mount host `~/.pi`.
- Dependency installation uses operator `pnpm` 12.6.0 at `/home/scetrov/.local/share/pnpm/bin/pnpm`, outside the sandbox, with `--ignore-scripts`. The operator explicitly approved migration to `pnpm-lock.yaml` for 11.2. `pnpm import` and `pnpm install --frozen-lockfile --ignore-scripts` ran; `package-lock.json` was removed. Do not reintroduce npm installation. CI downloads the exact pnpm 12.6.0 tarball and verifies its recorded SHA-512 before running frozen installation with scripts disabled.
- Publication remains npm/pi.dev. Pi host peers stay `"*"` and are not bundled. Do not install TypeBox 1.3.34 beside Pi: `@earendil-works/pi-ai` 0.87.1 depends on TypeBox 1.3.27. Tool schemas import `Type` from `@earendil-works/pi-ai`.
- Loading the Pi extension must not open a socket, install Blender files, or persist credentials. Real Blender tests must require their success marker. Blender can exit zero after a Python assertion failure.

## What is already true

Sections 1–9 are checked, including 8.9 and 9.10. The implementation is an early local bridge, not a published release. Do not claim Windows, physical viewport capture, marketplace publication, or release qualification.

Pi-side behavior the next session must not regress:

- `extensions/index.ts` only registers tools, commands, and lifecycle hooks. `extensions/transport.ts` connects only when a command or tool opens the session, and only to literal `127.0.0.1`.
- `BridgeSession` keeps one hello connection, drops in-memory credentials on disconnect, shutdown, and reload, and reconciles a retained mutation only with `operation.outcome`. It never resubmits `operation.execute`. Restart, lookup failure, or missing re-pair is `outcome_unknown`.
- Nine sequential tools live in `extensions/tools.ts`. Mutation, cancel, checkpoint, and restore stay inactive until full trust. Auth is injected by the session, never taken from the model.
- Commands are `/blender-setup`, `/blender-pair`, `/blender-diagnostics`, `/blender-trust`, and `/blender-version`. Print mode writes text and does not open dialogs. Pairing codes are never read from discovery.
- **9.7:** `/blender-setup` locates the bundled extension, checks `extensions/blender-extension-release.json` against a canonical SHA-256 of the installable tree, explains the destination, and copies files only after interactive approval. Print mode never installs. Digest or manifest mismatch aborts with an integrity error. Unmanaged directories and symbolic links are not modified. Setup does not enable the extension, launch Blender, or change trust. The release metadata digest must be regenerated when a payload file changes; `tests/unit/setup.test.mjs` fails if it drifts.
- **9.8:** `extensions/diagnostics.ts` and `BridgeSession.assess()` distinguish absent, disabled, stale, unpaired, unauthorized, incompatible, and unreachable bridges. Optional missing capabilities disable only those features. Protocol major mismatch keeps control disabled. A symlinked discovery directory is not followed.
- **9.9:** Isolated tests cover registration, lifecycle, schemas, rendering, setup consent, truncation, artifact validation, compatibility, and tool error paths under `tests/unit/`.
- **9.10:** `package.json` `files` includes `bridge/` but excludes `__pycache__` and `*.pyc`. `npm pack --ignore-scripts` produced a tarball with no `dependencies`, no bundled peers, and no `node_modules`. `pi install npm:<tarball>` in a private Pi home installed one package. Pi's loader then registered the five commands and nine tools from the installed directory. At the time of the 9.10 test, installed `skills/` had no `SKILL.md`; `tests/unit/pack.test.mjs` now exercises the pinned Pi skill loader on the packed tarball's seven skills, but a fresh full CLI install test is still due before release. Pi does not map a filesystem `npm:/path.tgz` settings source back to the installed package name on a later resolve; the installed directory path does load.

`skills/` now contains seven routed skills plus `.gitkeep`.

## Validation already recorded

Network-isolated Bubblewrap, project writable, no network. Latest checks: `tsc --noEmit` and `node --experimental-strip-types --test` for the Pi unit tests, including `tests/unit/setup.test.mjs`, `tests/unit/diagnostics.test.mjs`, `tests/unit/commands.test.mjs`, `tests/unit/session.test.mjs`, `tests/unit/tools.test.mjs`, and `tests/unit/pack.test.mjs`. The 9.10 Pi install used the extra read-only global `node_modules` mount named above.

Earlier real Blender 5.2.2 probes `tests/prototypes/inspection_blender.py` and `tests/prototypes/capture_blender.py` printed `BLENDER_INSPECTION_OK` and `BLENDER_CAPTURE_OK`. Those probes are not a full release qualification.

## Current state and next task

Tasks 10.1–11.6 are checked, including newly approved 11.2a and 11.2b to repair Pi notification delivery and bridge checkpoint list/restore before end-to-end validation. `extensions/transport.ts` validates wire events and `BridgeSession.recentActivity()` presents bounded non-secret progress/completion. The bridge lists verified checkpoints and accepts restore proposals; it never opens a checkpoint merely on a wire request. Artist confirmation is still mandatory. The canonical release metadata digest was regenerated; regenerate it again if any bridge or bundled schema changes.

The genuine separate-process Pi-to-Blender headless test is `tests/integration/pi_client_headless.mjs` + `tests/prototypes/pi_headless_blender.py`; it passed locally via `scripts/run_blender_smoke.py` using approved read-only Node 24.21.0 and Blender 5.2.2 mounts, isolated network/process/home and only project writable. Seven Blender success markers passed including adversarial wire, approval, file-load, artist workflows, and performance. `npm run validate` passed locally: 76 Node and 94 Python unit tests, format/lint/typecheck/spelling. See `docs/headless-e2e.md`, `docs/adversarial-test-coverage.md`, `docs/performance-validation.md`. Headless cannot validate physical viewport capture, dialog visuals, or interactive undo; the E2E test checks the undo receipt, and separate GUI-oriented existing probes cover actual undo where available. **Remote Linux/Windows CI has not run.** `scripts/acquire_blender.py` archive extraction and Windows execution remain unverified remotely.

**11.7 is blocked** on CodeQL/Scorecard/dependency review/vulnerability scans: Blender 5.2.2 `--command extension validate dist/bridge` already passed offline, but there are no `codeql` or `scorecard` executables, no Git remote, and the default sandbox has no network. `osv-scanner` exists on the host but its database/network cannot be mounted or accessed inside the default sandbox without approval. Do not mark 11.7 or later tasks complete merely because local validation passed. Ask the operator for an approved remote-CI/scan path; never silently enable sandbox network or host credentials. Continue 11.8–12.10 after resolving this blocker and archive before final signed commit/PR.

Before the final signed conventional commit and pull request, archive the completed OpenSpec change, run pre-commit explicitly, and keep Agent and Model attribution trailers within the repository line-length limit. Never disable signing if signing fails. Archiving does not mean the separate release checklist is done.
