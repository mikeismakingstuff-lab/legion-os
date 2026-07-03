"""
pipeline_state.py
Legion OS — LangGraph Pipeline State Schema

Defines the typed passport State that flows through the LangGraph StateGraph.
The State carries ONLY routing/tracking markers. All content, scores, and
results live in SQLite and are referenced by mission_id.

Zero external dependencies — standard library only.
"""

from __future__ import annotations

import uuid
from typing import Optional, TypedDict

# ──────────────────────────────────────────────────────────────────────────────
# Valid values for ingest_mode
# ──────────────────────────────────────────────────────────────────────────────
_VALID_INGEST_MODES = frozenset({"direct", "shishi-odoshi", "hybrid"})

# ──────────────────────────────────────────────────────────────────────────────
# State definition
# ──────────────────────────────────────────────────────────────────────────────

class PipelineState(TypedDict):
    """
    Lightweight passport carried through the LangGraph StateGraph.

    Fields
    ------
    mission_id      : UUID4 string of the active mission.
    db_path         : Absolute path string to pipeline.db, or None to use the
                      production default resolved by src.db.get_connection().
    current_stage   : Name of the last-completed stage ('INGEST', 'PARSE', …).
                      Empty string before any stage has run.
    error_flag      : True if any stage returned an error dict or raised.
    error_detail    : Human-readable error description when error_flag is True.
    ingest_mode     : Echoed from mission calibration:
                      one of 'direct', 'shishi-odoshi', or 'hybrid'.
    batch_promoted  : True if a shishi-odoshi/hybrid threshold was crossed in
                      Stage 1 and the pending batch was promoted to 'received'.
    """

    mission_id:            str
    db_path:               Optional[str]
    current_stage:         str
    error_flag:            bool
    error_detail:          Optional[str]
    ingest_mode:           str
    batch_promoted:        bool
    blast_radius_exceeded: bool   # True when retraction circuit breaker fires (>15%)
    arbitration_resolved:  bool   # True when arbitration node clears for continuation
    is_compressed:         bool   # True if Headroom compression was run on the batch
    compression_ratio:     float  # Average compression ratio for the batch


# ──────────────────────────────────────────────────────────────────────────────
# Factory helper
# ──────────────────────────────────────────────────────────────────────────────

def make_initial_state(
    mission_id: str,
    db_path: Optional[str] = None,
    ingest_mode: str = "direct",
) -> PipelineState:
    """
    Return a fully-initialized PipelineState with safe defaults.

    Parameters
    ----------
    mission_id  : Must be a valid UUID4 string.
    db_path     : Absolute path string to pipeline.db, or None for default.
                  Passing a path that does not yet exist is valid — src.db
                  creates the file on first connection.
    ingest_mode : One of 'direct', 'shishi-odoshi', or 'hybrid'.

    Raises
    ------
    TypeError   : If mission_id or ingest_mode are not strings.
    ValueError  : If mission_id is not a valid UUID4, or ingest_mode is not
                  one of the three allowed values.
    TypeError   : If db_path is not a string or None.
    """
    # Validate mission_id
    if not isinstance(mission_id, str):
        raise TypeError(
            f"mission_id must be a string, got {type(mission_id).__name__}."
        )
    try:
        parsed = uuid.UUID(mission_id)
    except ValueError:
        raise ValueError(
            f"mission_id '{mission_id}' is not a valid UUID."
        )
    if parsed.version != 4:
        raise ValueError(
            f"mission_id '{mission_id}' must be a UUID version 4, "
            f"got version {parsed.version}."
        )

    # Validate db_path — existence check intentionally omitted:
    # src.db creates the file at first connection; tests pass temp paths.
    if db_path is not None and not isinstance(db_path, str):
        raise TypeError(
            f"db_path must be a string or None, got {type(db_path).__name__}."
        )

    # Validate ingest_mode
    if not isinstance(ingest_mode, str):
        raise TypeError(
            f"ingest_mode must be a string, got {type(ingest_mode).__name__}."
        )
    if ingest_mode not in _VALID_INGEST_MODES:
        raise ValueError(
            f"ingest_mode '{ingest_mode}' is not valid. "
            f"Must be one of: {sorted(_VALID_INGEST_MODES)}."
        )

    return PipelineState(
        mission_id=mission_id,
        db_path=db_path,
        current_stage="",
        error_flag=False,
        error_detail=None,
        ingest_mode=ingest_mode,
        batch_promoted=False,
        blast_radius_exceeded=False,
        arbitration_resolved=False,
        is_compressed=False,
        compression_ratio=1.0,
    )
