## ADDED Requirements

### Requirement: Discoverable Pi package
The npm package SHALL declare the `pi-package` keyword and an explicit Pi manifest exposing the Blender Pi extension and bundled workflow skills. Pi host libraries SHALL be peer dependencies where required by Pi packaging rules and MUST NOT be bundled as duplicate runtime instances.

#### Scenario: Packed package is inspected
- **WHEN** the npm package is packed and installed into an isolated Pi environment
- **THEN** Pi discovers the declared extension and skills without relying on undeclared files or globally installed dependencies

#### Scenario: Package is published
- **WHEN** the npm version becomes available in the registry
- **THEN** its manifest contains the metadata required for pi.dev package-gallery discovery

### Requirement: Bundled Blender bridge distribution
The npm and GitHub release artifacts SHALL include a reproducibly built GPL-3.0-only Blender 5.2+ extension or the exact verified assets needed to build it, with corresponding source and GPL notice alongside the MIT-licensed Pi package notices. The Pi package SHALL expose an approved setup path that locates the bundled artifact, verifies its digest, and guides or performs installation only after explicit user consent.

#### Scenario: Artist approves bridge installation
- **WHEN** the artist invokes setup and approves installation
- **THEN** the package installs or presents the bundled verified Blender extension and reports its installed location and version

#### Scenario: Artifact digest differs
- **WHEN** the bundled bridge digest does not match release metadata
- **THEN** setup aborts and reports an integrity error without installing the bridge

### Requirement: No silent system modification
Package loading SHALL NOT automatically install Blender files, launch Blender, alter Blender preferences, elevate trust, or persist credentials. Setup and repair operations MUST describe intended changes and require explicit approval before mutation.

#### Scenario: Pi loads the package
- **WHEN** Pi starts with the package enabled
- **THEN** no Blender installation, preference, process, or trust state is modified merely by loading the extension

### Requirement: Component and protocol compatibility reporting
The package SHALL report Pi package version, Blender extension version, Blender version, and negotiated protocol version. It SHALL fail closed with actionable guidance when mandatory versions are incompatible and SHALL degrade only optional features through advertised capability negotiation.

#### Scenario: Protocol major versions differ
- **WHEN** the Pi extension and Blender bridge advertise incompatible protocol major versions
- **THEN** control operations remain disabled and the artist receives specific upgrade or downgrade guidance

#### Scenario: Optional capability is unavailable
- **WHEN** the bridge lacks an optional capability supported by the Pi package
- **THEN** only the associated feature is disabled and status identifies the missing capability

### Requirement: Supported distribution boundary
Initial release documentation SHALL identify npm/pi.dev and GitHub Releases as supported distribution channels, Blender 5.2 as the minimum version, and the official Blender Extensions marketplace and MCP compatibility as out of scope.

#### Scenario: User reviews installation options
- **WHEN** a user reads installation documentation
- **THEN** supported channels, minimum versions, licensing assumptions, and excluded distribution targets are unambiguous
