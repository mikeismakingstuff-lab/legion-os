"""
Committee OS — Stage 0: Mission.

Accepts operator input, validates against the Architecture §0 contract,
persists to the `missions` table, and logs stage transitions to `pipeline_log`.

Contract
--------
INPUT
    mission_statement : str   — non-empty
    domain            : str   — must match a mode_id in system_modes.json
    calibration       : dict  — ingest_mode, volume_quality_slider,
                                min_content_length, active_emphasis_lenses

OUTPUT  → mission record dict matching the §0 JSON schema
FAILURE → dict with "error" key describing the rejection reason
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.db import get_connection

# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SYSTEM_MODES_PATH = _PROJECT_ROOT / "system_modes.json"

VALID_INGEST_MODES = {"shishi-odoshi", "direct", "hybrid"}


def _load_valid_domains() -> set[str]:
    """Load the set of valid mode_id values from system_modes.json."""
    with open(_SYSTEM_MODES_PATH, "r", encoding="utf-8") as f:
        modes = json.load(f)
    return {m["mode_id"] for m in modes}


def _iso_now() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _log(conn, mission_id: str, event: str, detail: str) -> None:
    """Write an entry to pipeline_log."""
    conn.execute(
        """
        INSERT INTO pipeline_log (log_id, mission_id, stage, event, detail, timestamp, error_code)
        VALUES (?, ?, 'MISSION', ?, ?, ?, NULL)
        """,
        (str(uuid.uuid4()), mission_id, event, detail, _iso_now()),
    )


# ──────────────────────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────────────────────

def _validate(
    mission_statement: str,
    domain: str,
    calibration: dict,
    valid_domains: set[str],
) -> str | None:
    """Return an error message string, or None if inputs are valid."""

    # mission_statement
    if not isinstance(mission_statement, str) or not mission_statement.strip():
        return "mission_statement must be a non-empty string."

    # domain
    if domain not in valid_domains:
        return (
            f"domain '{domain}' is not defined. "
            f"Valid domains: {sorted(valid_domains)}"
        )

    # calibration — ingest_mode
    ingest_mode = calibration.get("ingest_mode")
    if ingest_mode not in VALID_INGEST_MODES:
        return (
            f"calibration.ingest_mode must be one of {sorted(VALID_INGEST_MODES)}. "
            f"Got: '{ingest_mode}'"
        )

    # calibration — volume_quality_slider
    slider = calibration.get("volume_quality_slider")
    if not isinstance(slider, (int, float)) or not (0.0 <= slider <= 1.0):
        return "calibration.volume_quality_slider must be a float between 0.0 and 1.0."

    # calibration — min_content_length
    min_len = calibration.get("min_content_length")
    if not isinstance(min_len, int) or min_len < 0:
        return "calibration.min_content_length must be a non-negative integer."

    # calibration — active_emphasis_lenses
    lenses = calibration.get("active_emphasis_lenses", [])
    if not isinstance(lenses, list) or len(lenses) > 3:
        return "calibration.active_emphasis_lenses must be a list of at most 3 lens names."

    return None  # valid


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

def create_mission(
    mission_statement: str,
    domain: str,
    calibration: dict,
    db_path: Path | None = None,
) -> dict:
    """Create and persist a new mission.

    Returns the mission record dict on success, or an error dict on failure.
    """
    valid_domains = _load_valid_domains()

    # ── Validate ──────────────────────────────────────────────
    error = _validate(mission_statement, domain, calibration, valid_domains)
    if error:
        return {"error": error}

    # ── Build record ──────────────────────────────────────────
    mission_id = str(uuid.uuid4())
    timestamp = _iso_now()

    record = {
        "mission_id": mission_id,
        "statement": mission_statement.strip(),
        "domain": domain,
        "timestamp": timestamp,
        "calibration": {
            "ingest_mode": calibration["ingest_mode"],
            "volume_quality_slider": float(calibration["volume_quality_slider"]),
            "min_content_length": int(calibration["min_content_length"]),
            "active_emphasis_lenses": list(calibration.get("active_emphasis_lenses", [])),
        },
    }

    # ── Persist ───────────────────────────────────────────────
    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT INTO missions (mission_id, statement, domain, timestamp, calibration)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                record["mission_id"],
                record["statement"],
                record["domain"],
                record["timestamp"],
                json.dumps(record["calibration"]),
            ),
        )

        _log(conn, mission_id, "stage_start", "Mission creation initiated.")
        _log(conn, mission_id, "stage_complete", "Mission created successfully.")
        conn.commit()
    except Exception as exc:
        conn.rollback()
        return {"error": f"Database error: {exc}"}
    finally:
        conn.close()

    return record
