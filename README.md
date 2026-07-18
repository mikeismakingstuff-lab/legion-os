# Legion OS — Localized Data Ingestion & Processing Pipeline

Legion OS is a high-performance, deterministic data ingestion and processing pipeline designed to run locally with zero external cloud dependencies. It features a custom state machine, native context compression, and a futuristic tactical control center dashboard.

---

## 1. Directory Structure & File Map

```
E:\Legion
├── .agent/                 # Agent configuration and workflows
│   └── workflows/
│       └── committee-gatekeeper.md  # Adversarial code review workflow
├── public/                 # Frontend assets for the Control Center UI
│   ├── index.html          # Dashboard layout and UI panels
│   ├── styles.css          # CSS Grid column lock and sci-fi styling
│   └── scripts.js          # Telemetry, file tree, chat, and notepad client logic
├── src/                    # Backend source code
│   ├── __init__.py
│   ├── db.py               # SQLite connection helper (get_connection)
│   ├── init_db.py          # Database schema initialization script
│   ├── pipeline_state.py   # TypedDict state passport schema
│   ├── legion_graph.py     # Custom LegionStateMachine and node topology
│   ├── compression_engine.py # Headroom context compression wrapper
│   ├── web_server.py       # API server for the Control Center UI
│   ├── stage0_mission.py   # Mission calibration logic + SourceMapper (source_registry)
│   ├── stage1_ingest.py    # Ingestion, Shishi-Odoshi accumulation, web scraping
│   ├── stage2_parse.py     # Rule-based sentence splitting and classification
│   ├── stage3_filter.py    # 4-rule noise and duplicate filtering
│   ├── stage4_weigh.py     # Multi-lens scoring engine
│   ├── stage5_deliberate.py # Deterministic top-3 selection (no external LLM calls)
│   ├── stage6_output.py    # Output slot mapping and serialization
│   └── retraction_engine.py # Retraction blast-radius calculation & manual_review_queue
├── tests/                  # Pytest verification suite
│   ├── test_stage1.py to test_stage6.py  # Stage-specific unit tests
│   ├── test_retraction.py  # Retraction engine tests
│   ├── test_web_ingest.py  # Web scraping and ingestion tests
│   ├── test_phase1.py      # Config/schema/mission integrity tests
│   └── test_source_mapper.py # SourceMapper matching logic tests
├── music_tools/            # Music library tooling — separate concern from the core pipeline
│   ├── clean_music.py
│   ├── rename_music.py
│   ├── test_rename_music.py
│   └── RadioStation_ShishiOdoshi.xlsx
├── system_modes.json       # System configurations and thresholds
└── config.json             # Global configuration parameters
```

> **Note on `pipeline.db`:** despite appearing in earlier versions of this map,
> the active database is **not** stored in this directory by default.
> `src/db.py::_resolve_db_path()` resolves to
> `~/Documents/ContentPipeline/pipeline.db` (i.e. `C:\Users\<you>\Documents\ContentPipeline\pipeline.db`
> on Windows) unless the `COMMITTEE_OS_DATA_ROOT` environment variable is set.
> Any `pipeline.db` seen sitting in `E:\Legion` itself was created by an
> explicit `db_path` override (e.g. a script or test passing its own path) and
> is not the file the pipeline reads from or writes to during a normal run.

---

## 2. Database Schema Contract

All pipeline state and processed data are persisted in SQLite (`pipeline.db`) to enforce the **DB-as-Contract** pattern. The schema consists of the following tables:

### Core Pipeline Tables
1.  **`missions`** (Stage 0):
    *   `mission_id` (TEXT PRIMARY KEY): UUIDv4.
    *   `statement` (TEXT NOT NULL): The mission objective.
    *   `domain` (TEXT NOT NULL): Domain filter constraint.
    *   `timestamp` (TEXT NOT NULL): ISO-8601 creation time.
    *   `calibration` (TEXT NOT NULL): JSON string containing thresholds and weights.
2.  **`ingest_records`** (Stage 1):
    *   `ingest_id` (TEXT PRIMARY KEY): UUIDv4.
    *   `mission_id` (TEXT NOT NULL REFERENCES `missions`): Associated mission.
    *   `source` (TEXT NOT NULL): File path or URL source.
    *   `format` (TEXT NOT NULL): File format (e.g., `markdown`, `text`).
    *   `raw_content` (TEXT NOT NULL): Raw text content (cleared to `""` after compression).
    *   `timestamp` (TEXT NOT NULL): ISO-8601 timestamp.
    *   `status` (TEXT NOT NULL): Ingestion status (`pending` | `received`).
3.  **`parsed_units`** (Stage 2):
    *   `unit_id` (TEXT PRIMARY KEY): UUIDv4.
    *   `ingest_id` (TEXT NOT NULL REFERENCES `ingest_records`): Source record.
    *   `type` (TEXT NOT NULL): Classified type (`fact` | `figure` | `claim` | `instruction` | `unknown`).
    *   `content` (TEXT NOT NULL): Cleaned sentence-level text.
    *   `character_count` (INTEGER NOT NULL): Length of content.
    *   `status` (TEXT NOT NULL): Parsing status (`parsed`).
4.  **`filter_results`** (Stage 3):
    *   `unit_id` (TEXT PRIMARY KEY REFERENCES `parsed_units`): Associated unit.
    *   `status` (TEXT NOT NULL): Filter result (`pass` | `fail`).
    *   `fail_reason` (TEXT): Reason for failure (NULL if passed).
5.  **`lens_scores`** (Stage 4):
    *   `unit_id` (TEXT REFERENCES `parsed_units`): Associated unit.
    *   `lens` (TEXT NOT NULL): Lens name (e.g., `relevance`, `credibility`).
    *   `raw_score` (REAL NOT NULL): Raw score (0.0 to 1.0).
    *   `criteria_breakdown` (TEXT NOT NULL): JSON string detailing scoring criteria.
    *   `weighted_score` (REAL NOT NULL): Score multiplied by lens weight.
    *   *Primary Key:* `(unit_id, lens)`
6.  **`deliberation_results`** (Stage 5):
    *   `deliberation_id` (TEXT PRIMARY KEY): UUIDv4.
    *   `mission_id` (TEXT NOT NULL REFERENCES `missions`): Associated mission.
    *   `recommendations` (TEXT NOT NULL): JSON string of recommendations.
    *   `flags` (TEXT NOT NULL): JSON string of warning flags.
7.  **`pipeline_outputs`** (Stage 6):
    *   `output_id` (TEXT PRIMARY KEY): UUIDv4.
    *   `mission_id` (TEXT NOT NULL REFERENCES `missions`): Associated mission.
    *   `timestamp` (TEXT NOT NULL): ISO-8601 timestamp.
    *   `slots` (TEXT NOT NULL): JSON string mapping recommendations to output slots.
8.  **`pipeline_log`** (All Stages):
    *   `log_id` (TEXT PRIMARY KEY): UUIDv4.
    *   `mission_id` (TEXT NOT NULL): Associated mission.
    *   `stage` (TEXT NOT NULL): Stage name (e.g., `INGEST`, `PARSE`).
    *   `event` (TEXT NOT NULL): Event type (e.g., `stage_start`, `stage_complete`).
    *   `detail` (TEXT NOT NULL): Detailed description or error message.
    *   `timestamp` (TEXT NOT NULL): ISO-8601 timestamp.
    *   `error_code` (TEXT): Error code if applicable.

### Compression & UI Tables
9.  **`compressed_content`** (Context Compression):
    *   `ingest_id` (TEXT PRIMARY KEY REFERENCES `ingest_records`): Associated record.
    *   `compressed_data` (BLOB): Reversibly compressed text payload.
    *   `uncompressed_length` (INTEGER NOT NULL): Original character count.
    *   `compressed_length` (INTEGER NOT NULL): Compressed byte/character count.
    *   `compression_ratio` (REAL NOT NULL): Ratio of compressed to uncompressed length.
    *   `timestamp` (TEXT NOT NULL): Timestamp of compression.
10. **`chat_logs`** (Control Center UI):
    *   `id` (INTEGER PRIMARY KEY AUTOINCREMENT): Auto-incrementing ID.
    *   `mission_id` (TEXT NOT NULL): Associated mission.
    *   `sender` (TEXT NOT NULL): Sender identity (`User` | `Legion AI`).
    *   `message` (TEXT NOT NULL): Chat message text.
    *   `timestamp` (TEXT NOT NULL): Timestamp of message.
11. **`notepad_content`** (Control Center UI):
    *   `mission_id` (TEXT PRIMARY KEY): Associated mission.
    *   `content` (TEXT NOT NULL): Markdown notepad content.
    *   `timestamp` (TEXT NOT NULL): Last saved timestamp.

### Epistemic & Retraction Layer (Stage 3/4 Extension)
These tables back the parts of Legion not covered by the original Committee OS
spec: source auto-suggestion, contradiction resolution, and the human-gated
circuit breaker on retractions. All five are created by `src/init_db.py` but
were previously undocumented here.

12. **`source_registry`** (Stage 0 — `SourceMapper`):
    *   `source_id` (TEXT PRIMARY KEY).
    *   `domain` (TEXT NOT NULL): One of the 14 modes.
    *   `keyword` (TEXT NOT NULL): Mission-statement keyword to match, or `*` (wildcard fallback).
    *   `url` (TEXT NOT NULL): Suggested source URL.
    *   `priority` (INTEGER NOT NULL): Lower sorts first.
    *   Note: `stage0_mission.py::SourceMapper.map_mission_to_sources()` reads this
      table and is fully tested (`tests/test_source_mapper.py`), but as of this
      writing is **not called from `legion_graph.py`** — it exists and works,
      it just isn't wired into `node_ingest` yet.
13. **`classified_records`** (Stage 3/4 — epistemic layer):
    *   `record_id` (TEXT PRIMARY KEY).
    *   `chapter_id` (TEXT NOT NULL).
    *   `assertion_key` (TEXT NOT NULL): Groups records making the same claim.
    *   `verdict` (TEXT NOT NULL): `pass` | `fail` | `flagged`.
    *   `rubric_dependencies` (TEXT NOT NULL): JSON blob of evaluated criteria.
    *   `confidence_score` (REAL NOT NULL, 0.0–1.0).
    *   `supersedes_record_id` (TEXT REFERENCES `classified_records`): Set when a
        retraction replaces this record.
    *   `timestamp` (TEXT NOT NULL).
14. **`record_dependencies`**:
    *   `dependent_record_id`, `dependency_record_id` (both TEXT REFERENCES `classified_records`).
    *   Composite primary key. Used by `retraction_engine.py::project_blast_radius()`
        to compute how many downstream records a retraction would affect.
15. **`quarantine_log`**:
    *   `quarantine_id` (TEXT PRIMARY KEY).
    *   `unit_id` (TEXT NOT NULL REFERENCES `parsed_units`).
    *   `reason` (TEXT NOT NULL).
    *   `timestamp` (TEXT NOT NULL).
16. **`manual_review_queue`** (the retraction circuit breaker's human gate):
    *   `review_id` (TEXT PRIMARY KEY).
    *   `contested_key_a`, `contested_key_b`, `loser_key` (TEXT NOT NULL).
    *   `projected_blast_radius` (REAL NOT NULL): Percentage of active records affected.
    *   `affected_record_ids` (TEXT NOT NULL): JSON list.
    *   `timestamp` (TEXT NOT NULL).
    *   `status` (TEXT NOT NULL, default `'awaiting_human_review'`): one of
        `awaiting_human_review` | `approved` | `rejected`. **This is the only
        thing `node_arbitration` will accept as authorization to continue past
        a blocked retraction.** No API call, subprocess exit code, or committee
        opinion can set this value — only a human (or a future explicit approval
        action) updating the row directly.

---

## 3. State Machine & Routing Passport

The `LegionStateMachine` manages execution flow using a lightweight `PipelineState` passport:

```python
class PipelineState(TypedDict):
    mission_id:            str    # UUIDv4 of the active mission
    db_path:               Optional[str] # Path to SQLite database
    current_stage:         str    # Last-completed stage ('INGEST', 'PARSE', etc.)
    error_flag:            bool   # True if any stage failed
    error_detail:          Optional[str] # Error description
    ingest_mode:           str    # 'direct' | 'shishi-odoshi' | 'hybrid'
    batch_promoted:        bool   # True if pending batch was promoted to 'received'
    blast_radius_exceeded: bool   # True if retraction blast radius > 15%
    arbitration_resolved:  bool   # True if arbitration node clears continuation
    pending_review_id:     Optional[str]  # manual_review_queue.review_id awaiting human action
    is_compressed:         bool   # True if Headroom compression was run
    compression_ratio:     float  # Average compression ratio for the batch
```

### Routing Logic
*   **Ingest Promotion:** If `batch_promoted` is `True`, the router advances to `PARSE`. If `False` (still accumulating in shishi-odoshi mode), execution halts gracefully at `INGEST`.
*   **Error Handling:** If `error_flag` is `True`, execution routes to the `arbitration` node for manual review or automated retries.
*   **Retraction Circuit Breaker:** If a retraction is triggered, the `retraction_engine` calculates the blast radius. If it exceeds 15% of total parsed units, `blast_radius_exceeded` is set to `True`, halting execution for manual arbitration. **Arbitration only clears via a human setting `manual_review_queue.status` to `'approved'`** — an attached OpenRouter committee call (when `OPENROUTER_API_KEY` is set) is advisory only and cannot authorize continuation by itself.

---

## 4. Context Compression Flow

Legion OS uses a **"Measure Raw, Store Compressed"** strategy to optimize storage without losing downstream parsing fidelity:

```
[Ingestion Stream] ──> Measure Length/Metadata ──> Check Shishi-Odoshi Threshold
                                                               │
                                                       (If Promoted)
                                                               │
                                                               ▼
[compressed_content] <── Store BLOB ◄── Compress ◄── [Raw Text Payload]
                                                               │
                                                               ▼
                                                    Clear ingest_records.raw_content
```

### Zero-Amnesia Retrieval
When a downstream stage (e.g., Stage 2 Parse) needs the raw text, it calls `CompressionEngine.retrieve_uncompressed(ingest_id)`:
1.  It queries the `compressed_content` table for `ingest_id`.
2.  If found, it decompresses the BLOB and returns the original string.
3.  If not found (e.g., compression was skipped or failed), it falls back to reading the `raw_content` column in `ingest_records`.

---

## 5. Control Center API Endpoints

The backend web server (`src/web_server.py`) exposes the following endpoints:

*   **`GET /api/telemetry`**
    *   *Response:* `{"cpu": float, "ram": float, "latency": int, "token_count": int, "token_limit": int}`
*   **`GET /api/files`**
    *   *Response:* Nested JSON tree representing the workspace directory structure.
*   **`POST /api/preview`**
    *   *Request:* `{"path": "relative/path/to/file"}`
    *   *Security:* Resolves path using `.resolve()` and verifies it remains within the workspace root to prevent directory traversal.
    *   *Response:* `{"content": "file content text", "name": "filename.ext"}`
*   **`POST /api/chat`**
    *   *Request:* `{"message": "user message text", "mission_id": "optional-uuid"}`
    *   *Response:* `{"response": "AI generated response"}`
*   **`POST /api/notepad`**
    *   *Request (Save):* `{"action": "save", "content": "markdown text", "mission_id": "optional-uuid"}`
    *   *Request (Load):* `{"action": "load", "mission_id": "optional-uuid"}`
    *   *Response:* `{"status": "success"}` or `{"content": "markdown text"}`
*   **`GET /health`**
    *   *Response:* Basic liveness check.
*   **`GET /api/deliberation`**
    *   *Response:* `{"content": "..."}` — tails `committee_live.txt`, the running output
        of a `committee.py` subprocess. Unrelated to the Stage 5 `deliberation_results`
        table despite the shared name — this is the Control Center's live feed for
        the "Combined Session" panel, not pipeline deliberation output.
*   **`POST /api/committee`**
    *   *Request:* `{"message": "..."}`
    *   *Effect:* Spawns `committee.py` as a background subprocess against the
        message, on the burner OpenRouter key. No confirmation step — any typed
        message in the "Combined Session" UI panel triggers this immediately.
    *   *Response:* `{"status": "started"}`
*   **`POST /api/antigravity`**
    *   *Request:* `{"message": "..."}`
    *   *Response:* `{"response": "..."}`
