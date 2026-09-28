# GitHub repository controls (maintainer actions)

**Not yet verified:** this checkout began without a Git remote and the intended `scetrov/blender-pi` GitHub repository/settings may not exist. Files in `.github/` request review and automation but **do not enable** branch rules, private reporting, secret scanning, signing policy, or 2FA. Check settings on the actual hosted repository before claiming any control is active.

Before merging from outside contributors or publishing:

1. Protect the default branch with a ruleset requiring pull requests, at least one independent approving review where available, code-owner review for sensitive files, no self-approval, resolved conversations, up-to-date required CI, and no direct/force pushes. Record exceptions and actual enforcement in a maintainer audit. Keep signed-commit verification enabled and verify the signed commit policy applies to protected refs.
2. Turn on 2FA enforcement for organization members if hosted in an organization; for a personal account, verify the owner's 2FA and recovery arrangements without claiming org-wide enforcement. Designate a backup maintainer when feasible.
3. Enable GitHub secret scanning, push protection where supported, dependency graph, Dependabot alerts, and private vulnerability reporting. Test the private reporter flow at [the planned advisories endpoint](https://github.com/scetrov/blender-pi/security/advisories/new) without exposing a real secret. Provide a fallback confidential channel before public release if private reports cannot be enabled.
4. Restrict Actions permissions to read by default, disallow unreviewed third-party actions, protect release environments, require reviewer approval for privileged publishing, and configure npm trusted publishing without a long-lived publish token where supported.
5. Configure CODEOWNERS handles and issue/PR templates after confirming account and repo URL; this file is guidance, not evidence of setting activation. Record review history, response metrics, and OpenSSF badge answers from actual public evidence, not policy text.

Review settings at each release and after repository transfer. See [security policy](../SECURITY.md) and [governance](../GOVERNANCE.md).
