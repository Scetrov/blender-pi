---
name: blender-setup-diagnostics
description: Set up or diagnose the local Blender Pi bridge. Use for installation, Blender enablement, pairing, trust, compatibility, status, and connection failures.
license: MIT
compatibility: Pi package with Blender 5.2 or newer
---

# Set up and diagnose Blender Pi

See [curated references and a read-only example](references/examples.md).

The artist owns the open Blender session. Loading this package does not start the listener, install files, or grant trust. The bridge is GPL-3.0-only; Pi-side code is MIT. The package is pre-release; do not describe npm/pi.dev publication or platform qualification as complete.

1. Run `/blender-setup` to inspect the bundled bridge and its digest. Explain the proposed destination and obtain the interactive approval it requests before copying files. In non-interactive mode it prints instructions and makes no changes. Never bypass an integrity failure, overwrite an unmanaged installation, or enable the extension silently. If manual installation is necessary, follow the command's reported instructions.
2. Ask the artist to enable the installed Blender Pi extension in Blender 5.2+ and press **Start Local Listener** in its 3D View sidebar. Do not launch Blender or alter preferences on their behalf without a separate explicit request.
3. Use `/blender-diagnostics`, `/blender-version`, or `blender_status` to distinguish absent, disabled, stale discovery, unreachable, incompatible, unpaired, and unauthorized states. Follow the specific corrective action reported. A protocol major mismatch disables control; a missing optional capability disables only its feature. Do not infer compatibility from a package version alone.
4. Ask the artist to read the pairing ID and one-time code from Blender. Use `/blender-pair submit <pairing-id> <code> inspection` (or `full` only if the work requires trusted Python), then ask the artist to review and approve the requester details in Blender and use `/blender-pair poll <pairing-id>`. Never read codes from discovery, echo them into reports, or store credentials. Inspection also requires completed pairing.
5. Explain that **full trust is equivalent to Blender Run Script**: unrestricted Python may read or change user files, use network libraries, and start processes. It is not sandboxed. Use inspection trust for read-only bridge-owned operations. Check `/blender-trust` before requesting a mutation. Blender can revoke the session; stopping the listener or replacing the connection may require new pairing.
6. On a disconnect after submitting a mutation, check diagnostics and reconcile the retained outcome only after re-pairing with full trust. Never resubmit the same code automatically. If the outcome is unknown, inspect the live scene and request an explicit new decision.

If Blender's UI is blocked by non-yielding code, cancellation may not yet be received or observed; do not claim the operation stopped. Stop and surface unresolved setup or trust errors rather than weakening controls. For recovery after an operation, use the `blender-troubleshooting-recovery` skill.
