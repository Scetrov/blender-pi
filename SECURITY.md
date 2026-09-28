# Security policy

## Supported versions

No functional release or security-supported version exists yet. Once a stable version is published, this page will list maintained versions and end-of-support dates. Do not deploy the current scaffold for trusted Blender control.

## Report a vulnerability privately

**Do not open a public issue containing exploit details, credentials or affected scene data.** The intended private intake is [GitHub Private Vulnerability Reporting](https://github.com/scetrov/blender-pi/security/advisories/new). This repository has not yet been hosted or enabled for private reports; the link may be unavailable until the maintainer enables that setting. Enabling and testing private reporting is a **release prerequisite**. If it is unavailable, do not post the sensitive report publicly; wait for a verified private channel to be announced. We cannot promise a response time or coordinated disclosure process before a maintainer establishes them.

Include a minimal reproduction, affected version, impact, and a safe way to contact you. Avoid attaching actual secrets or client project data. Reports will be evaluated privately, with remediation and disclosure timing agreed where feasible.

## Scope and limitations

The eventual full-trust bridge will run unrestricted Blender Python under the artist's account. This is intentional Run Script-equivalent authority, not a security sandbox. Threats to report include unauthenticated scene access, trust bypass, secret leakage, artifact path escape, unauthorized external effects, and supply-chain issues. See [threat model](docs/threat-model.md) and [licensing boundary](docs/licensing.md).
