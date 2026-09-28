# Dependency update review

Dependabot checks npm dependencies and GitHub Actions monthly with bounded PR counts; no pip environment or third-party Blender Python package is currently supported. Add a new ecosystem only when a manifest for it is introduced. `typebox` and Pi host packages are peer dependencies with `"*"` per Pi's packaging contract; review the supported host API versions manually rather than claiming the bridge ships or pins the host's runtime copy.

For each update, verify the latest **applicable** released version and upstream provenance, registry tarball integrity and lockfile changes, license and transitive notices, maintenance/release notes, security advisories, compatibility with Node/Blender/Pi baselines, and platform-specific packages. Run `npm ci --ignore-scripts`, `npm run validate`, package inspection, and relevant real Blender 5.2 integration tests. Verify GitHub Actions commit SHA against the upstream release and pin the full SHA; do not merge automatic major upgrades without reviewer approval. Prefer removing unnecessary dependencies. Document justified exceptions and follow up on unresolved advisories before publication.

Dependabot PRs and labels alone do not establish that alerts, dependency review, branch protections, or human reviews are enabled on GitHub; verify hosted settings separately in [repository settings](repository-settings.md).
