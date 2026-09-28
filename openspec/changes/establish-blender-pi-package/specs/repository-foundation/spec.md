## ADDED Requirements

### Requirement: Complete open-source repository scaffold
The repository SHALL include an MIT license for Pi-side material and a GPL-3.0-only license for the Blender extension, with clear component boundaries and both notices/source included in distributed artifacts, plus README, changelog, security policy, contribution guide, code of conduct, governance policy, support policy, CODEOWNERS, issue forms, pull-request template, dependency update configuration, and documented release process. Documents SHALL describe current project behavior and controls rather than unsupported aspirations.

#### Scenario: Fresh checkout exposes project policies
- **WHEN** a contributor checks out the repository
- **THEN** all required project, contribution, security, governance, support, and release documents are present at documented locations

#### Scenario: Security reporting is private by default
- **WHEN** a user reads the security policy
- **THEN** it identifies supported versions and a non-public vulnerability reporting path without directing reporters to disclose vulnerabilities in a public issue

### Requirement: Least-privilege continuous integration
All GitHub Actions SHALL be pinned to reviewed immutable commit SHAs, declare least-privilege permissions, avoid privileged execution of untrusted pull-request code, and run repository formatting, linting, static analysis, unit tests, protocol conformance tests, package validation, and security checks appropriate to changed components.

#### Scenario: Pull request validation is unprivileged
- **WHEN** CI validates a pull request from an untrusted fork
- **THEN** it runs without release credentials, write permissions, or execution in a privileged pull-request-target context

#### Scenario: Workflow dependency is immutable
- **WHEN** a workflow uses a third-party action
- **THEN** the action reference is a verified full commit SHA with the source version documented by an adjacent comment or dependency record

### Requirement: Dependency and vulnerability management
The repository SHALL lock each build or runtime dependency with available integrity metadata, enable automated dependency updates, perform dependency review and vulnerability scanning, and document how maintainers assess, update, and remove dependencies. New dependencies MUST be checked for current applicable version, provenance, license, and maintenance status before adoption.

#### Scenario: Dependency manifest changes
- **WHEN** a pull request modifies a package manifest or lockfile
- **THEN** CI reports dependency-review and known-vulnerability findings before merge

### Requirement: Verifiable release artifacts
Release automation SHALL build npm and Blender artifacts from the tagged source, use protected and least-privilege publishing credentials, and publish checksums, an SBOM, provenance or attestations, compatibility metadata, and installation verification results. Publishing SHALL fail if validation or artifact integrity checks fail.

#### Scenario: Release is produced
- **WHEN** maintainers publish an approved version tag
- **THEN** npm and GitHub release artifacts identify the same source revision and include verifiable integrity and provenance information

#### Scenario: Release validation fails
- **WHEN** package installation, Blender extension validation, tests, or artifact verification fails
- **THEN** publishing stops without releasing a partial version

### Requirement: Truthful OpenSSF Best Practices evidence
The repository SHALL contain a root `.bestpractices.json` using official criterion field names and only evidence-backed statuses. Unknown, organizational, historical, or repository-setting claims without evidence MUST remain `?` or be documented as follow-up work. OpenSSF Scorecard results SHALL be treated as supporting evidence rather than proof of Best Practices criteria.

#### Scenario: Initial badge proposal is reviewed
- **WHEN** `.bestpractices.json` is validated
- **THEN** every `Met` answer has concrete public evidence and unsupported answers remain unknown

#### Scenario: Organizational control lacks evidence
- **WHEN** a criterion depends on organization-wide enforcement or operational history not visible in the repository
- **THEN** the project does not claim the criterion as met solely from policy text
