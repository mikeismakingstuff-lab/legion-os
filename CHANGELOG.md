# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- **Music Library Standardization**: Added `rename_music.py` and `tests/test_rename_music.py` for robust file matching and renaming.
- **Control Center UI**: Implemented a unified, localized control center for Legion OS with a sci-fi tactical aesthetic (`public/index.html`, `scripts.js`, `styles.css`).
- **Committee Diagnostic UI**: Added a Live Pipeline Feed widget and a dedicated diagnostic dashboard to the Control Center.
- **Telemetry & Monitoring**: Added real-time CPU, RAM, and token usage monitoring to the web server.

### Changed
- **Deterministic Deliberation**: Refactored `src/stage5_deliberate.py` to use a pure deterministic selection and ranking mechanism, removing external LLM dependencies.
- **Pipeline Output**: Updated `src/stage6_output.py` to handle the new deterministic `rationale_facts` structure.
- **Music Metadata Parsing**: Enhanced `clean_music.py` with structural parsing heuristics and UTF-8 encoding support.
- **Committee Protocol**: Updated `committee.py` to use the `nvidia/nemotron-3-super-120b-a12b:free` model for reliable deliberation and added live logging to `committee_live.txt`.
- **Context Compression**: Integrated the Headroom context compression library into the ingestion pipeline (`src/compression_engine.py`, `src/stage1_ingest.py`).

### Fixed
- **API Authorization**: Fixed a `NameError` and syntax error in `committee.py` related to API key formatting.
- **Chat Responses**: Resolved an issue where the Legion OS Control Center chat interface returned "User Safety: safe" instead of functional AI responses.
