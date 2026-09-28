# Release candidate checklist template

This is a maintainer checklist, not release automation. Do not publish from an unverified `0.0.0` scaffold.

- [ ] All implementation OpenSpec scenarios have evidence and the change is archived before the final signed commit/PR.
- [ ] Signed source tag approved by the maintainer; commit, tarball and bridge source/license boundaries verified.
- [ ] Linux x64 and Windows x64 real Blender 5.2 tests, npm pack/install, and extension validation pass.
- [ ] Dependency review, advisories, checksums, SBOMs, provenance and attestations match the same source revision.
- [ ] Protected environment and trusted npm publishing have been checked in GitHub/npm settings.
- [ ] Security private reporting, rulesets, reviews, secret scanning and 2FA settings verified separately.
- [ ] A separate release checklist tracks publication approval and *post-publication* verification of npm/pi.dev and GitHub artifacts.
