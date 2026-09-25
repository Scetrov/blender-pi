# Dependency adoption record

Checked npm's package metadata on 2026-09-23 before adding manifests. The runtime Blender bridge uses Blender's `bpy` and Python standard library only; no Blender-side pip install is planned. Pi supplies its own host libraries as **peers** (per [Pi package documentation](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/packages.md)); those peers must use `"*"` for host compatibility and are not copied into the npm package. Their exact installed tarball is controlled by the host Pi installation, not by this package's lockfile. Development tools will use exact versions and a committed npm lockfile with integrity fields for all resolved packages. Recheck releases, licenses and advisories when upgrading.

| Proposed package | Role | Latest applicable npm release checked | License | Registry SHA-512 integrity |
| --- | --- | --- | --- | --- |
| [`@earendil-works/pi-coding-agent`](https://www.npmjs.com/package/@earendil-works/pi-coding-agent) | Pi host peer types/API | 0.87.1 | MIT | `sha512-m8ArJUtVcQMSe1lLE/Ei7vX/JV7O39sWmWBsXV2NOU70F0qCp8GubA24pT3LnwTmM6LL2xV80/h6sQg85n69ew==` |
| [`typebox`](https://www.npmjs.com/package/typebox) | Pi host peer schema API | 1.3.34 | MIT | `sha512-wbnzrXXDW8xEFHDZZs2jo1MkhaYlKAY4FRhpBc1+2LF1fZVBGCXGdLEhA/Z/NBbgzJMFfeM8m7elKPa/+KxaUQ==` |
| [`typescript`](https://www.npmjs.com/package/typescript) | Dev-only type-checker | 7.0.2 | Apache-2.0 | `sha512-8FYau96o3NKOhbjKi/qNvG/W5jhzxkbdm5sj9AbZ/5T5sWqn3hJgLfGx27sRKZWTvyzCP8dLRBTf5tBTSRVUNA==` |
| [`@biomejs/biome`](https://www.npmjs.com/package/@biomejs/biome) | Dev-only formatter and lint | 2.5.14 | MIT OR Apache-2.0 | `sha512-0FabLIjd4M/dm8VFI86RMaLLdgepzbdfiAL2R8cr7V81OYYrP1w7Z73KfAwPK5h9SrEBXTzNG2y+mBwPo9xRnw==` |

**Provenance checked:** metadata comes from `https://registry.npmjs.org/<encoded-package-name>/latest`; registry entries name the upstream repositories (earendil-works/pi, sinclairzx81/typebox, microsoft/TypeScript, biomejs/biome), tarball URL and `dist.integrity`; each metadata entry included npm registry signatures. This confirms available registry metadata, **not** independent verification of the upstream source against a signed tag. Verify lockfile `integrity`, package contents, transitive/optional dependencies and any platform-specific binaries when adopting in task 2.3; audit vulnerabilities and preserve license notices before release. Do not claim an unverified third-party tarball is intrinsically trusted.

The official Blender 5.2.2 Linux test archive has SHA-256 `84098912789dc450e95697c4184fb8a90acbe5111c2ba4aede3fecb57806a168` from Blender's [published checksum file](https://download.blender.org/release/Blender5.2/blender-5.2.2.sha256); archive pinning for each CI OS belongs to task 11.1.
