# Release approval and public-artifact checklist

**Separate from the implementation OpenSpec change. Nothing below is complete by virtue of archiving that change.** This is a template for the release maintainer; leave every item unchecked until verified against the actual release. Do not publish while cross-platform CI fails, the release environment is unprotected, or security-reporting prerequisites are unresolved.

Release version: ______  Signed tag: ______  Commit SHA: ______  Approval record and approver: ______

## Before publication — require signed approval

- [ ] Choose a release version (not the development `0.0.0`) shared by `package.json` and `bridge/blender_manifest.toml`; verify compatibility metadata and changelog.
- [ ] Verify the source tag signature and source commit identity, and record the verifier, fingerprint and immutable SHA. Reject unsigned, untrusted, or mismatched tags.
- [ ] Confirm protected `main` and a **pre-existing, protected** GitHub release environment with required independent reviewer approval and restricted deployment branches/tags. A workflow that names an unconfigured environment is not protection.
- [ ] Confirm npm trusted publishing links this repository and the exact publishing workflow. Use short-lived OIDC identity; do not introduce a long-lived npm publish token. For the first-time package, the operator-approved bootstrap is a manual publish of the verified tarball using interactive npm authentication **after signed release approval**, with no CI publish token; record the registry result, then configure and verify OIDC for subsequent automated releases. Do not pretend OIDC has been configured or that manual publication has already occurred.
- [ ] Review successful Linux x64 and Windows x64 checks on the tagged revision: unit, real Blender 5.2, packaging/install/uninstall, CodeQL, dependency review, audit, secret scanning, license notices, and extension validation. Record any justified GUI-only test gap. No known failing acceptance test may be ignored silently.
- [ ] Build npm and Blender artifacts from the same tagged source without runtime downloads or lifecycle scripts. Rebuild and compare archive SHA-256; verify both contain matching version/compatibility information and GPL bridge source and MIT wire notices.
- [ ] Inspect checksums, SBOM (SPDX or CycloneDX), provenance and artifact attestations for both artifacts. Confirm digest/commit/version binding and verify attestations before upload.
- [ ] Obtain a **signed, recorded release approval** from an authorized maintainer in the protected release environment **before** any npm or GitHub publication. Record approver and timestamp above; no approval from an unprotected workflow run counts.

## After publication — verify public artifacts, not local build output

- [ ] Install the published npm version in an isolated Pi environment with scripts disabled; verify extension loading, skill discovery, peer behavior and the bundled bridge digest. Record registry URL, version and tarball integrity.
- [ ] Confirm the package appears in the pi.dev gallery and its listing points to the expected npm version and repository. If indexing is delayed, keep this unchecked and record a follow-up.
- [ ] Download GitHub Releases artifacts from the public release page; verify the signed tag, the uploaded checksums against **downloaded** bytes, and consistent source revision for npm and Blender ZIPs.
- [ ] Verify provenance and artifact attestations cryptographically against the public artifacts and trusted repository identity; inspect both SPDX/CycloneDX SBOMs for matching component versions, licenses and source identifiers.
- [ ] Check the published compatibility metadata against Blender 5.2+ and the actual protocol/package/bridge versions; exercise install/uninstall and, if a verified previous compatible pair exists, downgrade and recover using both components together. Otherwise document the first-release absence and verify revocation/uninstall/checkpoint recovery.
- [ ] Record the release URLs, digest evidence, CI run IDs, SBOM/provenance verification commands and outcomes, gallery observation date and any residual risks in a release record. Escalate integrity mismatches rather than changing checksums after publication.
