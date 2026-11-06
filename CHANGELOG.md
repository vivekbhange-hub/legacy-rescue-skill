# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-11-07

### Added
- Skills: `rescue-map`, `rescue-hotspots`, `rescue-dead-code`, `rescue-characterize`,
  `rescue-deps`, `rescue-strangler`, `rescue-refactor`, `rescue-plan`.
- Agents: `legacy-cartographer`, `safety-net-builder`, `upgrade-planner`.
- Helper scripts (Python 3.9+, standard library only): `inventory.py` (repo inventory),
  `hotspots.py` (churn x complexity, change coupling, knowledge risk),
  `dead_code_scan.py` (commented-out code, constant conditions, orphan files),
  `outdated_report.py` (risk-ordered upgrade path from package-manager output).
- Unit tests for every script and a repository structure test.
- Claude Code plugin marketplace manifest.
