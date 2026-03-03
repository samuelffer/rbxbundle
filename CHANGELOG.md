# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

## [0.5.7] - 2026-03-03

### Added
- Added a `CI` workflow that runs the test suite on `push` and `pull_request`.
- Added configurable Roblox bundle rules via `create_bundle(..., rules=...)`, `generate_summary(..., rules=...)`, and project-level `rbxbundle.json`.
- Added a formal `schema_version` for `rbxbundle.json` configs, with legacy v1 compatibility when the field is missing.
- Added `rbxbundle config validate [FILE]` to validate config schema and rule fields explicitly.
- Added a packaging smoke test in CI for the installed `rbxbundle` CLI entry point.

### Fixed
- Hardened CLI config loading so valid JSON with the wrong root type no longer crashes startup.
- Added regression coverage for invalid config roots, schema-version handling, and custom rule overrides.

## [0.5.6] - 2026-03-03

### Added
- Added `WARNINGS.txt` with placement and source-heuristic warnings for suspicious client/server script usage.
- Added `HIERARCHY_MIN.txt` as a reduced hierarchy view for scripts, remotes, bindables, common config objects, and key assets.
- Added `MANIFEST.json` with generator version, timestamp, input filename, SHA-256, and bundle counts.
- Added disabled-script metadata to exported script headers, `INDEX.csv`, and dependency graph nodes.
- Added summary entry-point sections for enabled client and server scripts.
- Added regression coverage for disabled metadata, warnings output, minimal hierarchy export, and manifest generation.

### Changed
- `SUMMARY.md` now highlights entry points, marks disabled scripts, and separates disabled scripts into their own section.
- Bundle guidance in `SUMMARY.md` now references the new manifest, warnings, and minimal hierarchy outputs.

### Fixed
- Fixed script execution-side classification so `Script` instances respect `RunContext` instead of relying only on class name.
- Fixed script export naming, metadata, and summary counts for `Script` instances running as client or server via `RunContext`.

## [0.5.5] - 2026-03-03

### Fixed
- Fixed `build` and `inspect` so relative file names also resolve from the default input directory.
- Fixed default Windows documents path detection for redirected folders such as OneDrive-backed Documents.

## [0.5.4] - 2026-03-03

### Fixed
- Fixed command-line routing so invalid arguments return an argparse error instead of opening interactive mode.

### Changed
- Default workspace for installed command-line usage now lives in `Documents/rbxbundle/`.
- The standalone `.exe` continues to use the folder where the executable is located.
- Updated README guidance for interactive mode, command-line usage, and default workspace paths.

## [0.5.3] - 2026-03-03

### Fixed
- Fixed packaged `.exe` startup so opening it without arguments no longer exits immediately.

### Changed
- Simplified startup behavior: launching without arguments now always opens interactive mode.
- Removed the startup mode toggle from settings and CLI help text.

## [0.5.2] - 2026-03-03

### Fixed
- Fixed config persistence defaults in argparse mode
- Fixed corrupted CLI and summary output text
- Added regression tests for CLI defaults and summary formatting

## [0.5.1] - 2026-03-02

### Fixed
- Fixed CLI config persistence to use a per-user config path instead of writing beside package files.
- Added support for `rbxbundle --version`.
- Normalized CLI status and error messages for clearer output.
- Updated tests to match the current dependency analysis failure message in `SUMMARY.md`.

## [0.5.0] - 2026-03-02

### Changed
- Moved the CLI entry point into the package as `rbxbundle._cli`.

### Fixed
- Updated the console script entry point to `rbxbundle._cli:main`.
- Ignored runtime config files in Git tracking.
- Bumped the package version to `0.5.0`.

## [0.4.1] - 2026-03-02

### Added
- Added client/server boundary alerts in summary generation.
- Improved dependency analysis reporting while keeping bundle generation working on dependency errors.

### Fixed
- Updated versioning and related test expectations.
