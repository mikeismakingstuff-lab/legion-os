"""
Committee OS — Stage 5: Deliberate.

The only stage where language model judgment is applied.
Takes weighted, pre-scored structured data. Returns synthesis.

Architecture §4 Contract
-------------------------
INPUT   : Top N scored units from Stage 4
PROCESS : 1. Gemini Reactive Formatter:
             - Formats scored units into the handoff contract schema.
             - Must not interpret, score, rank, or summarize.
             - On error: fallback schema with {"gemini_error": true}.
          2. Qwen Deliberation Engine:
             - Receives handoff package.
             - Synthesizes and ranks top 3 units into slots 1A, 2A, 3A.
             - 429 handling: exponential backoff [15s, 30s, 60s], max 3 retries,
               min 20s between requests. Distinguish quota from rate limit.
             - On malformed output: retry once. On second failure: halt pipeline.
          3. Validate Qwen output contract:
             - Slots must be exactly 1A, 2A, 3A with no duplicates.
             - Confidence must be float 0.0 - 1.0.
             - Partial/complete failure: halt pipeline (pipeline_halt event).
          Store to deliberation_results table.
OUTPUT  : deliberation result records per §4 schema
"""

import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.db import get_connection
from src.stage4_weigh import get_top_scored_units

# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config.json"

_last_qwen_request_time = 0.0


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(conn, mission_id: str, event: str, detail: str,
         error_code: str | None = None) -> None:
    conn.execute(
        """
        INSERT INTO pipeline_log
            (log_id, mission_id, stage, event, detail, timestamp, error_code)
        VALUES (?, ?, 'DELIBERATE', ?, ?, ?, ?)
        """,
        (str(uuid.uuid4()), mission_id, event, detail, _iso_now(), error_code),
    )


def _load_config() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ──────────────────────────────────────────────────────────────
# Gemini Formatter
# ──────────────────────────────────────────────────────────────

GEMINI_SYSTEM_PROMPT = (
    "You are a data formatter. You receive a JSON payload of scored pipeline units. "
    "Your only task is to reformat this payload into the handoff schema defined below. "
    "You do not interpret, summarize, score, rank, or modify content values. "
    "You do not add commentary. If the input is malformed or fields are missing, "
    "output a JSON error object: {\"error\": \"description of structural issue\", \"raw_passthrough\": true} "
    "Output valid JSON only. No prose. No markdown. No explanation."
)


def _call_gemini(payload: dict) -> dict:
    """Call Gemini to format the payload, or return mock/fallback on error."""
    payload_str = json.dumps(payload, indent=2)
    api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        # Mock mode: perform deterministic formatting
        return _mock_gemini_format(payload)

    # Real API call
    from google import genai
    from google.genai import types
    try:
        client = genai.Client(api_key=api_key)
        config = types.GenerateContentConfig(
            system_instruction=GEMINI_SYSTEM_PROMPT,
            max_output_tokens=8500,
            response_mime_type="application/json",
        )
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=payload_str,
            config=config,
        )
        return json.loads(response.text)
    except Exception as exc:
        # Fallback behavior: Package Stage 4 output into a minimal valid handoff schema
        # with all non-essential fields set to null and {"gemini_error": true} appended.
        fallback = {
            "mission_id": payload.get("mission_id"),
            "mission_statement": payload.get("mission_statement"),
            "top_units": [
                {
                    "unit_id": u["unit_id"],
                    "content": u["content"],
                    "lens_scores": u.get("lens_scores"),
                    "aggregate_score": u.get("aggregate_score"),
                }
                for u in payload.get("top_units", [])
            ],
            "unit_count": len(payload.get("top_units", [])),
            "gate_threshold": payload.get("gate_threshold"),
            "gemini_error": True,
        }
        return fallback


def _mock_gemini_format(payload: dict) -> dict:
    return {
        "mission_id": payload.get("mission_id"),
        "mission_statement": payload.get("mission_statement"),
        "top_units": [
            {
                "unit_id": u["unit_id"],
                "content": u["content"],
                "lens_scores": u.get("lens_scores"),
                "aggregate_score": u.get("aggregate_score"),
            }
            for u in payload.get("top_units", [])
        ],
        "unit_count": len(payload.get("top_units", [])),
        "gate_threshold": payload.get("gate_threshold"),
    }


# ──────────────────────────────────────────────────────────────
# Qwen Deliberation Engine
# ──────────────────────────────────────────────────────────────

QWEN_SYSTEM_PROMPT = (
    "You are a deliberation engine. You receive a JSON payload containing pre-scored pipeline "
    "units. Each unit has already been evaluated by deterministic rubrics. Your only task is to "
    "synthesize the scores and select the top 3 units by merit, returning them as a ranked JSON "
    "output in the schema defined below. You do not re-score. You do not ingest new data. "
    "You do not adopt a role or persona. You do not add unsolicited commentary or explanation "
    "outside the defined schema. Base your ranking on aggregate_score values and lens_score "
    "distributions provided. Output valid JSON only. No prose. No markdown. No preamble."
)


def _call_qwen_with_retry(handoff_payload: dict, conn, mission_id: str) -> dict:
    """Call Qwen with exponential backoff and retry logic."""
    global _last_qwen_request_time

    api_key = os.environ.get("QWEN_API_KEY")
    if not api_key:
        # Mock mode
        return _mock_qwen_deliberate(handoff_payload)

    from openai import OpenAI, RateLimitError

    base_url = os.environ.get("QWEN_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    client = OpenAI(api_key=api_key, base_url=base_url)

    backoffs = [15.0, 30.0, 60.0]
    max_retries = 3
    attempt = 0

    payload_str = json.dumps(handoff_payload, indent=2)

    while True:
        # Enforce minimum 20s between requests
        elapsed = time.time() - _last_qwen_request_time
        if elapsed < 20.0:
            time.sleep(20.0 - elapsed)

        _last_qwen_request_time = time.time()
        _log(conn, mission_id, "ai_call", f"Calling Qwen (attempt {attempt + 1})")

        try:
            response = client.chat.completions.create(
                model="qwen3-next-80b-a3b-instruct",
                messages=[
                    {"role": "system", "content": QWEN_SYSTEM_PROMPT},
                    {"role": "user", "content": payload_str},
                ],
                max_tokens=4096,
                response_format={"type": "json_object"},
            )
            return json.loads(response.choices[0].message.content)

        except RateLimitError as rl_exc:
            # Distinguish rate_limit_exceeded (retry) from insufficient_quota (halt immediately)
            err_msg = str(rl_exc).lower()
            if "quota" in err_msg or "insufficient" in err_msg or "credit" in err_msg:
                _log(conn, mission_id, "ai_error", f"Qwen quota exceeded: {rl_exc}", "insufficient_quota")
                raise rl_exc

            if attempt >= max_retries:
                _log(conn, mission_id, "ai_error", f"Qwen rate limit retries exhausted: {rl_exc}", "rate_limit_exceeded")
                raise rl_exc

            sleep_dur = backoffs[attempt]
            _log(conn, mission_id, "ai_error", f"Qwen 429 rate limit: sleeping {sleep_dur}s. Error: {rl_exc}", "rate_limit_exceeded")
            time.sleep(sleep_dur)
            attempt += 1

        except Exception as exc:
            # Other errors (e.g. connection issues)
            if attempt >= max_retries:
                _log(conn, mission_id, "ai_error", f"Qwen call failed: {exc}", "api_error")
                raise exc
            sleep_dur = backoffs[attempt]
            time.sleep(sleep_dur)
            attempt += 1


def _mock_qwen_deliberate(handoff_payload: dict) -> dict:
    """Mock Qwen deliberation for testing."""
    top_units = handoff_payload.get("top_units", [])
    # Sort by aggregate score descending
    sorted_units = sorted(top_units, key=lambda x: x.get("aggregate_score", 0.0), reverse=True)

    recommendations = []
    slots = ["1A", "2A", "3A"]

    for idx, unit in enumerate(sorted_units[:3]):
        recommendations.append({
            "rank": str(idx + 1),
            "slot": slots[idx],
            "unit_id": unit["unit_id"],
            "rationale": f"Mock rationale for unit {unit['unit_id']} with score {unit.get('aggregate_score')}",
            "confidence": round(0.9 - idx * 0.1, 2),
        })

    return {
        "mission_id": handoff_payload.get("mission_id"),
        "deliberation_id": str(uuid.uuid4()),
        "recommendations": recommendations,
        "flags": [],
    }


# ──────────────────────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────────────────────

def _validate_qwen_output(output: dict, handoff_payload: dict) -> str | None:
    """Validate Qwen output contract.

    Returns error message if invalid, or None if valid.
    """
    if not isinstance(output, dict):
        return "Output must be a JSON object."

    if output.get("mission_id") != handoff_payload.get("mission_id"):
        return "mission_id mismatch."

    if "deliberation_id" not in output:
        return "Missing deliberation_id."

    recs = output.get("recommendations")
    if not isinstance(recs, list):
        return "recommendations must be a list."

    # Verify we have exactly 3 recommendations
    if len(recs) != 3:
        return f"Expected exactly 3 recommendations, got {len(recs)}."

    slots_seen = set()
    valid_slots = {"1A", "2A", "3A"}
    valid_ranks = {"1", "2", "3", 1, 2, 3}

    top_unit_ids = {u["unit_id"] for u in handoff_payload.get("top_units", [])}

    for idx, rec in enumerate(recs):
        if not isinstance(rec, dict):
            return f"Recommendation {idx} is not an object."

        rank = rec.get("rank")
        slot = rec.get("slot")
        unit_id = rec.get("unit_id")
        rationale = rec.get("rationale")
        confidence = rec.get("confidence")

        if rank not in valid_ranks:
            return f"Invalid rank '{rank}' in recommendation {idx}."

        if slot not in valid_slots:
            return f"Invalid slot '{slot}' in recommendation {idx}."

        if slot in slots_seen:
            return f"Duplicate slot '{slot}'."
        slots_seen.add(slot)

        if unit_id not in top_unit_ids:
            return f"unit_id '{unit_id}' not in top_units."

        if not isinstance(rationale, str) or not rationale.strip():
            return f"Missing rationale in recommendation {idx}."

        if not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0):
            return f"Invalid confidence '{confidence}' in recommendation {idx}."

    if slots_seen != valid_slots:
        return f"Missing slots. Expected exactly 1A, 2A, 3A, got {slots_seen}."

    return None


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

def deliberate_mission(
    mission_id: str,
    db_path: Path | None = None,
) -> dict:
    """Run the Stage 5 Deliberation stage for a mission."""
    conn = get_connection(db_path)
    try:
        # ── Fetch mission statement ───────────────────────────
        row = conn.execute(
            "SELECT statement FROM missions WHERE mission_id = ?",
            (mission_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"mission_id '{mission_id}' not found.")
        mission_statement = row["statement"]

        cfg = _load_config()
        gate_threshold = cfg.get("gate_threshold", 0.55)
        top_n = cfg.get("top_units_to_deliberation", 5)

        # ── Fetch top scored units ────────────────────────────
        top_units = get_top_scored_units(mission_id, limit=top_n, db_path=db_path)
        if not top_units:
            # Complete failure (0 valid recommendations): halt pipeline
            _log(conn, mission_id, "pipeline_halt", "No units passed the gate threshold.")
            conn.commit()
            raise ValueError("No units passed the gate threshold. Pipeline halted.")

        _log(conn, mission_id, "stage_start", f"Deliberation started with {len(top_units)} units.")

        # ── 1. Gemini Formatter ───────────────────────────────
        gemini_input = {
            "mission_id": mission_id,
            "mission_statement": mission_statement,
            "top_units": top_units,
            "unit_count": len(top_units),
            "gate_threshold": gate_threshold,
        }

        try:
            handoff_payload = _call_gemini(gemini_input)
        except Exception as gemini_exc:
            _log(conn, mission_id, "ai_error", f"Gemini formatter failed: {gemini_exc}", "gemini_error")
            # Fallback schema
            handoff_payload = {
                "mission_id": mission_id,
                "mission_statement": mission_statement,
                "top_units": top_units,
                "unit_count": len(top_units),
                "gate_threshold": gate_threshold,
                "gemini_error": True,
            }

        # ── 2. Qwen Deliberation ──────────────────────────────
        # We try once, and on malformed output we retry once.
        qwen_output = None
        validation_err = None

        for attempt in range(2):
            try:
                qwen_output = _call_qwen_with_retry(handoff_payload, conn, mission_id)
                validation_err = _validate_qwen_output(qwen_output, handoff_payload)
                if validation_err is None:
                    break
                _log(conn, mission_id, "ai_error", f"Qwen output validation failed (attempt {attempt + 1}): {validation_err}", "validation_error")
            except Exception as qwen_exc:
                _log(conn, mission_id, "ai_error", f"Qwen call failed (attempt {attempt + 1}): {qwen_exc}", "qwen_error")
                if attempt == 1:
                    # Second failure: halt pipeline
                    _log(conn, mission_id, "pipeline_halt", "Qwen deliberation failed twice.")
                    conn.commit()
                    raise qwen_exc

        if validation_err is not None:
            # Second failure: halt pipeline
            _log(conn, mission_id, "pipeline_halt", f"Qwen output validation failed twice: {validation_err}")
            conn.commit()
            raise ValueError(f"Qwen output validation failed: {validation_err}")

        # ── Persist results ───────────────────────────────────
        deliberation_id = qwen_output["deliberation_id"]
        conn.execute(
            """
            INSERT OR REPLACE INTO deliberation_results (deliberation_id, mission_id, recommendations, flags)
            VALUES (?, ?, ?, ?)
            """,
            (
                deliberation_id,
                mission_id,
                json.dumps(qwen_output["recommendations"]),
                json.dumps(qwen_output.get("flags", [])),
            ),
        )

        _log(conn, mission_id, "stage_complete", f"Deliberation complete: {deliberation_id}")
        conn.commit()
        return qwen_output

    except Exception as exc:
        conn.rollback()
        raise exc
    finally:
        conn.close()
