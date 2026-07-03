"""
legion_graph.py
Legion OS — LangGraph StateGraph (Full Lifecycle)

Full pipeline topology from Ingest through Output:

    ingest ──[check_ingest_promotion]──► parse
                                    └──► pending ──► END

    parse ──[should_halt]──► filter ──[should_halt]──► weigh
                ▼(err)                    ▼(err)
               END                        END

    weigh ──[check_retraction_blast_radius]──► deliberate
                                         └──► arbitration ──► weigh (retry)
                                                         └──► deliberate (clear)
                                                         └──► END (fatal)

    deliberate ──[should_halt]──► output ──► END
                    ▼(err)
                   END

Conditional Routers
───────────────────
check_ingest_promotion(state)
    batch_promoted=True  → "continue" → "parse"
    batch_promoted=False → "pending"  → "pending" (graceful accumulation hold)

check_retraction_blast_radius(state)
    blast_radius_exceeded=True → "arbitrate" → "arbitration"
    error_flag=True            → "halt"      → END
    else                       → "continue"  → "deliberate"

check_arbitration(state)
    arbitration_resolved=True, error_flag=False → "continue"  → "deliberate"
    arbitration_resolved=False, error_flag=False → "retry"    → "weigh"
    error_flag=True                              → "halt"     → END
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path



from src.db import get_connection
from src.pipeline_state import PipelineState
from src.retraction_engine import ManualReviewRequired, apply_retraction
from src.stage1_ingest import get_received_records
from src.stage2_parse import parse_ingest_record
from src.stage3_filter import filter_units
from src.stage4_weigh import weigh_units
from src.stage5_deliberate import deliberate_mission
from src.stage6_output import generate_pipeline_output


# ──────────────────────────────────────────────────────────────────────────────
# Routing helpers — pure functions, no side effects
# ──────────────────────────────────────────────────────────────────────────────

def should_halt(state: PipelineState) -> str:
    """Generic halt gate used between parse→filter→weigh→deliberate→output.

    Returns 'halt' if error_flag is set, 'continue' otherwise.
    """
    return "halt" if state.get("error_flag", False) else "continue"


def check_ingest_promotion(state: PipelineState) -> str:
    """Route after the ingest node.

    Returns
    -------
    'continue' — batch has been promoted to 'received'; safe to parse.
    'pending'  — batch is still accumulating (shishi-odoshi / hybrid hold).
    'halt'     — ingest error_flag set; terminate.
    """
    if state.get("error_flag", False):
        return "halt"
    return "continue" if state.get("batch_promoted", False) else "pending"


def check_retraction_blast_radius(state: PipelineState) -> str:
    """Route after the weigh node.

    Returns
    -------
    'arbitrate' — retraction circuit breaker fired (blast radius > 15%).
    'halt'      — a non-retraction error is flagged; terminate.
    'continue'  — no retraction issue; proceed to deliberate.
    """
    if state.get("blast_radius_exceeded", False):
        return "arbitrate"
    if state.get("error_flag", False):
        return "halt"
    return "continue"


def check_arbitration(state: PipelineState) -> str:
    """Route after the arbitration node.

    Returns
    -------
    'continue' — arbitration resolved; proceed to deliberate.
    'retry'    — arbitration unresolved; loop back to weigh for re-evaluation.
    'halt'     — fatal error during arbitration; terminate.
    """
    if state.get("error_flag", False):
        return "halt"
    if state.get("arbitration_resolved", False):
        return "continue"
    return "retry"


# ──────────────────────────────────────────────────────────────────────────────
# Node wrappers
# Contract: accept PipelineState → return partial state dict update.
# NEVER raise — all exceptions caught and converted to error_flag=True.
# ──────────────────────────────────────────────────────────────────────────────

def node_ingest(state: PipelineState) -> dict:
    """Stage 1 node — determines whether the ingest batch has been promoted.

    Queries `ingest_records` for this mission. If received records exist,
    compresses them via CompressionEngine, stores the BLOBs, clears the raw_content
    in ingest_records, and sets `batch_promoted=True`.
    """
    mission_id = state["mission_id"]
    db_path = Path(state["db_path"]) if state.get("db_path") else None
    try:
        received = get_received_records(mission_id=mission_id, db_path=db_path)
        if received:
            from src.compression_engine import compression_engine

            ratios = []
            for rec in received:
                ingest_id = rec["ingest_id"]
                raw_text = rec["raw_content"]

                # Compress and store in compressed_content
                metrics = compression_engine.compress_record(
                    ingest_id=ingest_id,
                    raw_text=raw_text,
                    db_path=db_path,
                )
                ratios.append(metrics["compression_ratio"])

                # Clear raw_content in ingest_records to save space
                conn = get_connection(db_path)
                try:
                    conn.execute(
                        "UPDATE ingest_records SET raw_content = '' WHERE ingest_id = ?",
                        (ingest_id,),
                    )
                    conn.commit()
                except Exception as db_exc:
                    print(f"[INGEST] Failed to clear raw_content for {ingest_id}: {db_exc}")
                finally:
                    conn.close()

            avg_ratio = sum(ratios) / len(ratios) if ratios else 1.0

            return {
                "current_stage": "INGEST",
                "batch_promoted": True,
                "ingest_mode": state.get("ingest_mode", "direct"),
                "is_compressed": True,
                "compression_ratio": avg_ratio,
            }
        # No received records yet — batch is still accumulating
        return {
            "current_stage": "INGEST",
            "batch_promoted": False,
            "is_compressed": False,
            "compression_ratio": 1.0,
        }
    except Exception as exc:
        return {
            "error_flag": True,
            "error_detail": f"[INGEST] {exc}",
            "current_stage": "INGEST",
        }


def node_pending(state: PipelineState) -> dict:
    """Graceful accumulation hold — batch not yet promoted.

    This terminal node is reached when the shishi-odoshi fill_threshold has
    not been crossed. The graph exits cleanly. The external orchestrator
    should call ingest_record() with more data, then re-invoke the graph.
    """
    return {
        "current_stage": "PENDING",
        "error_flag": False,
        "error_detail": (
            "Shishi-odoshi accumulation in progress. "
            "Re-invoke graph once fill threshold is met."
        ),
    }


def node_parse(state: PipelineState) -> dict:
    """Stage 2 node — parses all received ingest records for this mission.

    Fetches all received ingest IDs from DB and calls parse_ingest_record()
    for each. Errors on individual records are logged in state detail but
    do not halt the entire stage unless ALL records fail.
    """
    mission_id = state["mission_id"]
    db_path = Path(state["db_path"]) if state.get("db_path") else None
    db_path_arg = db_path  # preserve for stage call

    try:
        conn = get_connection(db_path)
        try:
            rows = conn.execute(
                "SELECT ingest_id FROM ingest_records "
                "WHERE mission_id = ? AND status = 'received'",
                (mission_id,),
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            return {
                "error_flag": True,
                "error_detail": (
                    f"[PARSE] No received ingest records found for mission '{mission_id}'."
                ),
                "current_stage": "PARSE",
            }

        errors = []
        for row in rows:
            ingest_id = row["ingest_id"]
            result = parse_ingest_record(
                ingest_id=ingest_id,
                mission_id=mission_id,
                db_path=db_path_arg,
            )
            # parse_ingest_record returns list; error dict has "error" key
            if result and isinstance(result[0], dict) and "error" in result[0]:
                errors.append(f"ingest_id={ingest_id}: {result[0]['error']}")

        if errors and len(errors) == len(rows):
            # Every record failed — hard error
            return {
                "error_flag": True,
                "error_detail": f"[PARSE] All records failed: {'; '.join(errors)}",
                "current_stage": "PARSE",
            }

        partial_warn = f" (partial errors: {'; '.join(errors)})" if errors else ""
        return {"current_stage": f"PARSE{partial_warn}"}

    except Exception as exc:
        return {
            "error_flag": True,
            "error_detail": f"[PARSE] {exc}",
            "current_stage": "PARSE",
        }


def node_filter(state: PipelineState) -> dict:
    """Stage 3 node — eliminates structurally disqualified units."""
    mission_id = state["mission_id"]
    db_path = Path(state["db_path"]) if state.get("db_path") else None
    try:
        filter_units(mission_id=mission_id, db_path=db_path)
        return {"current_stage": "FILTER"}
    except Exception as exc:
        return {
            "error_flag": True,
            "error_detail": f"[FILTER] {exc}",
            "current_stage": "FILTER",
        }


def node_weigh(state: PipelineState) -> dict:
    """Stage 4 node — scores passing units and checks retraction circuit breaker.

    After scoring, queries `manual_review_queue` for any blocked retractions
    for this mission. If found, sets blast_radius_exceeded=True so the router
    can divert to arbitration.
    """
    mission_id = state["mission_id"]
    db_path = Path(state["db_path"]) if state.get("db_path") else None
    try:
        weigh_units(mission_id=mission_id, db_path=db_path)

        # ── Retraction circuit breaker check ──────────────────────────────────
        # After scoring, check if any retraction for this mission was previously
        # blocked (blast radius > 15%) and is queued for manual resolution.
        conn = get_connection(db_path)
        try:
            pending_row = conn.execute(
                """
                SELECT review_id, projected_blast_radius
                FROM manual_review_queue
                WHERE contested_key_a IN (
                    SELECT DISTINCT assertion_key FROM classified_records
                )
                ORDER BY timestamp DESC
                LIMIT 1
                """
            ).fetchone()
        finally:
            conn.close()

        if pending_row:
            blast_pct = pending_row["projected_blast_radius"]
            return {
                "current_stage": "WEIGH",
                "blast_radius_exceeded": True,
                "error_detail": (
                    f"Retraction circuit breaker active: "
                    f"blast radius {blast_pct:.2f}% > 15% threshold. "
                    f"Review ID: {pending_row['review_id']}"
                ),
            }

        return {
            "current_stage": "WEIGH",
            "blast_radius_exceeded": False,
        }

    except ManualReviewRequired as exc:
        # apply_retraction raised directly — surface to arbitration
        return {
            "current_stage": "WEIGH",
            "blast_radius_exceeded": True,
            "error_detail": f"[WEIGH/RETRACTION] {exc}: {exc.payload}",
        }
    except Exception as exc:
        return {
            "error_flag": True,
            "error_detail": f"[WEIGH] {exc}",
            "current_stage": "WEIGH",
        }


def node_arbitration(state: PipelineState) -> dict:
    """Arbitration gate — OpenRouter committee / manual-review step.

    Behaviour:
    - If OPENROUTER_API_KEY is set: calls committee.py logic via subprocess
      to generate a resolution recommendation. Sets arbitration_resolved=True
      on acceptance.
    - If no API key: logs the blockage detail and sets arbitration_resolved=False
      (triggers a 'retry' loop back to weigh for re-evaluation after manual fix).
    - On any exception: sets error_flag=True (fatal — exits to END).

    The arbitration node does NOT call apply_retraction() itself — that is the
    operator's responsibility after reviewing manual_review_queue. It only
    determines whether the pipeline can safely continue.
    """
    mission_id = state["mission_id"]
    db_path = Path(state["db_path"]) if state.get("db_path") else None
    error_detail = state.get("error_detail", "")

    try:
        api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()

        if api_key:
            # ── Committee arbitration via OpenRouter ──────────────────────────
            # Build a focused spec for the committee describing the retraction
            # conflict, then invoke committee.py to get a resolution recommendation.
            import subprocess
            import tempfile

            spec_content = (
                f"# Retraction Arbitration Request\n\n"
                f"## Mission ID\n{mission_id}\n\n"
                f"## Blocked Retraction Detail\n{error_detail}\n\n"
                f"## Resolution Required\n"
                f"Review the manual_review_queue entry above. "
                f"Assess whether the retraction should proceed or be discarded. "
                f"Output a JSON object: "
                f'`{{"decision": "proceed"|"discard", "rationale": "..."}}`'
            )
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False, encoding="utf-8"
            ) as f:
                spec_path = f.name
                f.write(spec_content)

            committee_script = str(
                Path(__file__).resolve().parent.parent / "committee.py"
            )

            result = subprocess.run(
                ["python", committee_script],
                input=spec_content,
                capture_output=True,
                text=True,
                timeout=180,
                encoding="utf-8",
            )

            Path(spec_path).unlink(missing_ok=True)

            if result.returncode != 0:
                return {
                    "current_stage": "ARBITRATION",
                    "arbitration_resolved": False,
                    "error_detail": (
                        f"[ARBITRATION] Committee returned non-zero exit. "
                        f"Stderr: {result.stderr[:500]}"
                    ),
                }

            # Committee succeeded — mark resolved so router continues to deliberate
            return {
                "current_stage": "ARBITRATION",
                "arbitration_resolved": True,
                "blast_radius_exceeded": False,
                "error_flag": False,
                "error_detail": (
                    f"Arbitration resolved via OpenRouter committee. "
                    f"Pipeline cleared for deliberation."
                ),
            }

        else:
            # ── No API key — log and hold for manual resolution ───────────────
            # Persist the unresolved arbitration event to pipeline_log so the
            # operator can take action, then signal a retry loop.
            conn = get_connection(db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO pipeline_log
                        (log_id, mission_id, stage, event, detail, timestamp, error_code)
                    VALUES (?, ?, 'DELIBERATE', 'pipeline_halt', ?, datetime('now'), ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        mission_id,
                        f"Arbitration hold: {error_detail}",
                        "blast_radius_exceeded",
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            return {
                "current_stage": "ARBITRATION",
                "arbitration_resolved": False,
                "error_detail": (
                    "Arbitration hold: no OPENROUTER_API_KEY set. "
                    "Resolve manual_review_queue entry and re-invoke graph."
                ),
            }

    except Exception as exc:
        return {
            "error_flag": True,
            "error_detail": f"[ARBITRATION] Fatal error: {exc}",
            "current_stage": "ARBITRATION",
        }


def node_deliberate(state: PipelineState) -> dict:
    """Stage 5 node — Gemini + Qwen synthesis, selects top 3 slots."""
    mission_id = state["mission_id"]
    db_path = Path(state["db_path"]) if state.get("db_path") else None
    try:
        deliberate_mission(mission_id=mission_id, db_path=db_path)
        return {"current_stage": "DELIBERATE"}
    except Exception as exc:
        return {
            "error_flag": True,
            "error_detail": f"[DELIBERATE] {exc}",
            "current_stage": "DELIBERATE",
        }


def node_output(state: PipelineState) -> dict:
    """Stage 6 node — reads deliberation_results from DB, writes pipeline_outputs."""
    mission_id = state["mission_id"]
    db_path = Path(state["db_path"]) if state.get("db_path") else None
    try:
        generate_pipeline_output(mission_id=mission_id, db_path=db_path)
        return {"current_stage": "OUTPUT"}
    except Exception as exc:
        return {
            "error_flag": True,
            "error_detail": f"[OUTPUT] {exc}",
            "current_stage": "OUTPUT",
        }


# ──────────────────────────────────────────────────────────────────────────────
# State Machine Execution Engine (Zero-Dependency)
# ──────────────────────────────────────────────────────────────────────────────

class LegionStateMachine:
    """
    Zero-dependency, pure Python execution engine for the Legion OS pipeline.
    Replaces the third-party langgraph StateGraph compilation framework.

    Maintains identical node routing logic, error-catching wrappers, and
    provides an .invoke() interface for backward compatibility.
    """

    def __init__(self, retry_limit: int = 3):
        self.retry_limit = retry_limit

    def _persist_state(self, state: PipelineState) -> None:
        """Save the PipelineState tracking keys to the pipeline_state table in SQLite.

        Ensures the pipeline handles manual gates safely without in-memory amnesia.
        """
        db_path = Path(state["db_path"]) if state.get("db_path") else None
        conn = get_connection(db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pipeline_state (
                    mission_id TEXT PRIMARY KEY,
                    state TEXT
                )
                """
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO pipeline_state (mission_id, state)
                VALUES (?, ?)
                """,
                (state["mission_id"], json.dumps(state)),
            )
            conn.commit()
        finally:
            conn.close()

    def invoke(self, state: PipelineState) -> PipelineState:
        """Execute the full pipeline lifecycle from Ingest through Output.

        Parameters
        ----------
        state : The initial PipelineState passport.

        Returns
        -------
        PipelineState
            The final updated PipelineState passport.
        """
        # Ensure state is a mutable copy to avoid side effects for caller
        state = dict(state)

        # ── 1. Ingest (Stage 1) ───────────────────────────────────────────────
        state.update(node_ingest(state))
        self._persist_state(state)

        route = check_ingest_promotion(state)
        if route == "pending":
            state.update(node_pending(state))
            self._persist_state(state)
            return state
        elif route == "halt":
            return state

        # ── 2. Parse (Stage 2) ────────────────────────────────────────────────
        state.update(node_parse(state))
        self._persist_state(state)
        if should_halt(state) == "halt":
            return state

        # ── 3. Filter (Stage 3) ───────────────────────────────────────────────
        state.update(node_filter(state))
        self._persist_state(state)
        if should_halt(state) == "halt":
            return state

        # ── 4. Weigh (Stage 4) & Arbitration Loop ─────────────────────────────
        retries = 0
        while retries < self.retry_limit:
            state.update(node_weigh(state))
            self._persist_state(state)

            route = check_retraction_blast_radius(state)
            if route == "continue":
                break
            elif route == "halt":
                return state
            elif route == "arbitrate":
                # Divert to manual/committee arbitration gate
                state.update(node_arbitration(state))
                self._persist_state(state)

                arb_route = check_arbitration(state)
                if arb_route == "continue":
                    break
                elif arb_route == "halt":
                    return state
                elif arb_route == "retry":
                    retries += 1
                    continue

        if retries >= self.retry_limit:
            state["error_flag"] = True
            state["error_detail"] = (
                f"[WEIGH] Retraction arbitration retry limit ({self.retry_limit}) exceeded."
            )
            self._persist_state(state)
            return state

        # ── 5. Deliberate (Stage 5) ───────────────────────────────────────────
        state.update(node_deliberate(state))
        self._persist_state(state)
        if should_halt(state) == "halt":
            return state

        # ── 6. Output (Stage 6) ───────────────────────────────────────────────
        state.update(node_output(state))
        self._persist_state(state)

        return state


# ──────────────────────────────────────────────────────────────────────────────
# Module-level compiled instance (import-time convenience singleton)
# ──────────────────────────────────────────────────────────────────────────────
compiled_graph = LegionStateMachine()

