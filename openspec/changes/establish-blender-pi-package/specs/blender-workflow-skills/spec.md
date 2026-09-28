## ADDED Requirements

### Requirement: Portable discoverable skills
The package SHALL provide valid Agent Skills-compatible skill directories with matching kebab-case names, clear routing descriptions, relative references, and no reliance on maintainer-specific absolute paths. Pi SHALL discover the skills through the package manifest.

#### Scenario: Package is installed in a new environment
- **WHEN** Pi loads the published package
- **THEN** each declared Blender skill is discoverable and its referenced files resolve within the package

### Requirement: Workflow-domain coverage
The skill set SHALL cover setup and diagnostics, scene inspection and organization, modeling, materials and node systems, animation and rigging, rendering and visual review, and troubleshooting and recovery. Skills SHALL direct broad tasks through trusted Python rather than claiming that a constrained helper catalog covers Blender.

#### Scenario: Artist requests material and shading work
- **WHEN** Pi routes the task to the relevant skill
- **THEN** the skill covers state inspection, Blender 5.2 API discovery, bounded material or node changes, progress, and visual verification

#### Scenario: Artist requests unsupported domain detail
- **WHEN** local guidance lacks a version-specific API detail
- **THEN** the skill directs Pi to inspect the running Blender API or authoritative documentation rather than inventing a plausible symbol

### Requirement: Safe artist-led workflow guidance
Every mutating workflow skill SHALL require Pi to inspect relevant live state, explain a bounded operation, declare expected effects and risk, preserve the artist's intent, avoid unrelated changes, report progress when useful, inspect the result, and obtain visual evidence when appearance matters. Skills MUST stop and surface unresolved errors rather than continuing with speculative mutations.

#### Scenario: Modeling task is requested
- **WHEN** Pi prepares a modeling mutation
- **THEN** it inspects current mode, selection, relevant objects, and constraints before submitting a bounded execution request

#### Scenario: Visual result matters
- **WHEN** a task changes form, composition, materials, lighting, or rendering
- **THEN** the workflow captures and evaluates visual evidence rather than inferring quality solely from successful execution

### Requirement: Blender context and API discipline
Skills SHALL prefer Blender's data API for deterministic changes where practical, treat `bpy.ops` as context-sensitive, reacquire datablocks after undo or file changes, avoid retaining hidden interpreter state, and divide long work into cooperative stages. Guidance MUST identify Run Script-equivalent authority and distinguish ordinary undo from checkpoint recovery.

#### Scenario: Operator requires context
- **WHEN** a workflow needs a context-sensitive Blender operator
- **THEN** the skill directs Pi to inspect or establish the required mode, area, active object, and selection before invocation

#### Scenario: Work may run for a long time
- **WHEN** a workflow includes many items, rendering, baking, or simulation
- **THEN** the skill directs Pi to stage the work, emit progress, and check cooperative cancellation at safe boundaries

### Requirement: Skill validation and examples
CI SHALL validate skill frontmatter, names, descriptions, relative references, and packaged discovery. Examples SHALL target Blender 5.2+, use non-destructive defaults, declare expected effects, and be tested or syntax-checked at the strongest practical level.

#### Scenario: Skill reference is missing from package
- **WHEN** validation encounters a nonexistent referenced file
- **THEN** package validation fails before release

#### Scenario: Example uses a removed API
- **WHEN** Blender integration validation detects that an example is incompatible with the supported baseline
- **THEN** CI fails with the affected skill and API reference identified
