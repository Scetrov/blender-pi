# Local agent execution guidance

For short-lived project build/test commands, use the `bubblewrap-isolation` skill's network-isolated sandbox by default. The project root remains the only writable host mount. System Python (`/usr/bin/python3`) is already available via the standard read-only `/usr` mount.

The operator also authorizes **read-only** mounts of these exact local installations when required for project validation:

- Node.js: `/home/scetrov/.nvm/versions/node/v24.21.0` (for `npm run validate` and package tests).
- Blender: `/home/scetrov/software/blender-5.2.2-linux-x64` (for real Blender 5.2.2 tests).

Create only the mountpoint parent directories needed for these paths; do not mount the home directory, expose credentials, enable network access, grant devices/sockets, or make either installation writable. These paths are local test fixtures, not portable project dependencies. If an installation is missing or a different path/version is needed, ask before expanding sandbox access. Record the mounts and residual limitations when reporting validation.

## Package installation

Use the operator-installed `pnpm` 12.6.0 (`/home/scetrov/.local/share/pnpm/bin/pnpm`) for dependency installation. That is the latest npm release checked for this decision (MIT, registry integrity `sha512-PvaPlRyxEawgS0paFvCy3fDaVqluBBPoHYVdnwtV75JnFHCQKOHNAMQFwsX7e56OxNxGd3yAXQNzwvL/AP0g7A==`). Do not download another package manager, and do not run `npm install` or `npm ci` for the same job.

`pnpm` is more secure than npm for this repository because it keeps a non-hoisted, content-addressable store and can refuse lifecycle scripts. Running it outside Bubblewrap is **not** more secure than the sandbox. The standard sandbox has no network and must not gain a host store, home directory, or credentials, so it cannot fetch registry tarballs. That is why installation is the one host-side exception.

- Outside the sandbox, install only with `pnpm install --frozen-lockfile --ignore-scripts` when `pnpm-lock.yaml` already covers the request.
- A lockfile update is allowed only when the task is to add or upgrade a dependency, or the operator explicitly approves a lockfile migration. Verify the latest applicable release, license, and registry integrity before dependency upgrades, then run `pnpm install --ignore-scripts`. Do not drop `--ignore-scripts`.
- If a package cannot be used without a lifecycle script, stop and ask. Do not enable scripts globally.
- Do not mount `~/.local/share/pnpm`, the home directory, or credential paths into Bubblewrap. After installation, run tests and builds inside the sandbox against the project `node_modules` that pnpm wrote.
- pnpm is the local installer only. Publication remains the npm registry and pi.dev. Pi host peers stay `"*"` and are not bundled.
- The operator approved migration from `package-lock.json` to `pnpm-lock.yaml` for cross-platform CI in task 11.2. Keep the pnpm lockfile frozen for ordinary installations.
