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
│   ├── stage0_mission.py   # Mission calibration logic
│   ├── stage1_ingest.py    # Ingestion and Shishi-Odoshi accumulation
│   ├── stage2_parse.py     # Rule-based sentence splitting and classification
│   ├── stage3_filter.py    # 4-rule noise and duplicate filtering
│   ├── stage4_weigh.py     # Multi-lens scoring engine
│   ├── stage5_deliberate.py # Recommendation and flag aggregation
│   ├── stage6_output.py    # Output slot mapping and serialization
│   └── retraction_engine.py # Retraction blast-radius calculation
├── tests/                  # Pytest verification suite
│   ├── test_stage1.py to test_stage6.py  # Stage-specific unit tests
│   ├── test_retraction.py  # Retraction engine tests
│   └── test_web_ingest.py  # Web scraping and ingestion tests
├── pipeline.db             # Active SQLite database (created on first run)
├── system_modes.json       # System configurations and thresholds
└── config.json             # Global configuration parameters
```

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
    is_compressed:         bool   # True if Headroom compression was run
    compression_ratio:     float  # Average compression ratio for the batch
```

### Routing Logic
*   **Ingest Promotion:** If `batch_promoted` is `True`, the router advances to `PARSE`. If `False` (still accumulating in shishi-odoshi mode), execution halts gracefully at `INGEST`.
*   **Error Handling:** If `error_flag` is `True`, execution routes to the `arbitration` node for manual review or automated retries.
*   **Retraction Circuit Breaker:** If a retraction is triggered, the `retraction_engine` calculates the blast radius. If it exceeds 15% of total parsed units, `blast_radius_exceeded` is set to `True`, halting execution for manual arbitration.

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
