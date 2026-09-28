# GitHub repository controls (maintainer actions)

**Verified 2026-09-28:** the public `Scetrov/blender-pi` repository has an active `mainline` default-branch ruleset (ID 24114048) with required signatures, PR and scanning rules, plus enabled private vulnerability reporting, secret scanning and push protection. The legacy branch-protection API returned 404 but is **not** evidence that the modern ruleset is absent. The `release` environment endpoint returned 404; no protected publishing gate is verified. 2FA enforcement, actual review enforcement, and release controls still need maintainer confirmation. See [Best Practices evidence](best-practices-assessment.md).

Before merging from outside contributors or publishing:

1. Protect the default branch with a ruleset requiring pull requests, at least one independent approving review where available, code-owner review for sensitive files, no self-approval, resolved conversations, up-to-date required CI, and no direct/force pushes. Record exceptions and actual enforcement in a maintainer audit. Keep signed-commit verification enabled and verify the signed commit policy applies to protected refs.
2. Turn on 2FA enforcement for organization members if hosted in an organization; for a personal account, verify the owner's 2FA and recovery arrangements without claiming org-wide enforcement. Designate a backup maintainer when feasible.
3. Recheck secret scanning, push protection, dependency graph, Dependabot alerts, and private vulnerability reporting at release time. Private reporting is currently enabled, but the reporter flow at [the advisories endpoint](https://github.com/scetrov/blender-pi/security/advisories/new) still needs a non-sensitive test. Provide a fallback confidential channel before public release if private reports cannot be enabled.
4. Restrict Actions permissions to read by default, disallow unreviewed third-party actions, protect release environments, require reviewer approval for privileged publishing, and configure npm trusted publishing without a long-lived publish token where supported.
5. Configure CODEOWNERS handles and issue/PR templates after confirming account and repo URL; this file is guidance, not evidence of setting activation. Record review history, response metrics, and OpenSSF badge answers from actual public evidence, not policy text.

Review settings at each release and after repository transfer. See [security policy](../SECURITY.md) and [governance](../GOVERNANCE.md).
