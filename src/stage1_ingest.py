"""
Committee OS — Stage 1: Ingest.

Receives and registers raw data.  No transformation.  No interpretation.

Three ingestion modes (Architecture §1):
  1. Shishi-odoshi — passive accumulation.  Data arrives as individual records
     with status "pending".  When accumulated unit count reaches the fill
     threshold the batch flips to "received" and Stage 2 may begin.
       fill_threshold = base_unit_count * (1.0 - slider_value)
  2. Direct — operator-supplied data, immediately "received".
  3. Hybrid — both simultaneously; merged at ingest stage.

Contract
--------
INPUT
    mission_id : str            — valid mission UUID already in `missions`
    source     : str            — origin description
    format     : str            — data format label
    raw_content: str            — non-empty raw payload
    db_path    : Path | None    — override for testing

OUTPUT  → ingest record dict per §1 schema
FAILURE → Source unreachable or empty → log, flag, skip.  Do not halt.
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


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(conn, mission_id: str, event: str, detail: str,
         error_code: str | None = None) -> None:
    conn.execute(
        """
        INSERT INTO pipeline_log
            (log_id, mission_id, stage, event, detail, timestamp, error_code)
        VALUES (?, ?, 'INGEST', ?, ?, ?, ?)
        """,
        (str(uuid.uuid4()), mission_id, event, detail, _iso_now(), error_code),
    )


def _load_mode_config(domain: str) -> dict | None:
    """Return the mode entry from system_modes.json for the given domain."""
    with open(_SYSTEM_MODES_PATH, "r", encoding="utf-8") as f:
        modes = json.load(f)
    for m in modes:
        if m["mode_id"] == domain:
            return m
    return None


def _get_mission(conn, mission_id: str) -> dict | None:
    """Retrieve the mission record.  Returns None if not found."""
    row = conn.execute(
        "SELECT mission_id, statement, domain, timestamp, calibration "
        "FROM missions WHERE mission_id = ?",
        (mission_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "mission_id": row["mission_id"],
        "statement": row["statement"],
        "domain": row["domain"],
        "timestamp": row["timestamp"],
        "calibration": json.loads(row["calibration"]),
    }


# ──────────────────────────────────────────────────────────────
# Core: ingest a single record
# ──────────────────────────────────────────────────────────────

def ingest_record(
    mission_id: str,
    source: str,
    format: str,
    raw_content: str,
    db_path: Path | None = None,
) -> dict:
    """Ingest a single data record under the given mission.

    Behaviour depends on the mission's calibration.ingest_mode:
      - "direct"        → status immediately set to "received"
      - "shishi-odoshi" → status set to "pending"; a threshold check runs
                          to potentially promote the entire pending batch
      - "hybrid"        → same as shishi-odoshi (accumulable), but also
                          usable alongside direct calls in the same mission

    Returns the ingest record dict on success, or an error dict on failure.
    """
    # ── Validate inputs ───────────────────────────────────────
    if not isinstance(raw_content, str) or not raw_content.strip():
        return {"error": "raw_content is empty or not a string. Skipping."}

    if not isinstance(source, str) or not source.strip():
        return {"error": "source is empty or not a string. Skipping."}

    conn = get_connection(db_path)
    try:
        # ── Fetch mission ─────────────────────────────────────
        mission = _get_mission(conn, mission_id)
        if mission is None:
            return {"error": f"mission_id '{mission_id}' not found."}

        calibration = mission["calibration"]
        ingest_mode = calibration["ingest_mode"]

        _log(conn, mission_id, "stage_start",
             f"Ingest initiated — mode: {ingest_mode}, source: {source}")

        # ── Determine initial status ──────────────────────────
        if ingest_mode == "direct":
            status = "received"
        else:
            # shishi-odoshi and hybrid: accumulate as pending
            status = "pending"

        # ── Build and persist record ──────────────────────────
        ingest_id = str(uuid.uuid4())
        timestamp = _iso_now()

        conn.execute(
            """
            INSERT INTO ingest_records
                (ingest_id, mission_id, source, format, raw_content, timestamp, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (ingest_id, mission_id, source.strip(), format.strip(),
             raw_content, timestamp, status),
        )

        record = {
            "ingest_id": ingest_id,
            "mission_id": mission_id,
            "source": source.strip(),
            "format": format.strip(),
            "raw_content": raw_content,
            "timestamp": timestamp,
            "status": status,
        }

        # ── Shishi-odoshi / hybrid threshold check ────────────
        promoted_ids = []
        if ingest_mode in ("shishi-odoshi", "hybrid"):
            promoted_ids = _check_threshold(conn, mission_id, calibration)
            if promoted_ids:
                # Update our own record's status in the return value
                # if it was part of the promoted batch
                if ingest_id in promoted_ids:
                    record["status"] = "received"

        _log(conn, mission_id, "stage_complete",
             f"Ingest complete — ingest_id: {ingest_id}, status: {record['status']}"
             + (f", batch promoted: {len(promoted_ids)} records"
                if promoted_ids else ""))

        conn.commit()
        return record

    except Exception as exc:
        conn.rollback()
        return {"error": f"Database error: {exc}"}
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────
# Shishi-odoshi threshold logic
# ──────────────────────────────────────────────────────────────

def _check_threshold(conn, mission_id: str, calibration: dict) -> list[str]:
    """Check if pending records have reached the fill threshold.

    fill_threshold = base_unit_count * (1.0 - slider_value)

    If the count of pending records >= fill_threshold, all pending records
    for this mission are promoted to status "received".

    Returns the list of promoted ingest_ids (empty if threshold not met).
    """
    slider_value = calibration["volume_quality_slider"]
    domain = None

    # Retrieve domain from mission to look up base_unit_count
    row = conn.execute(
        "SELECT domain FROM missions WHERE mission_id = ?",
        (mission_id,),
    ).fetchone()
    if row:
        domain = row["domain"]

    mode_config = _load_mode_config(domain) if domain else None
    # base_unit_count: use default_min_length from mode config as the
    # mode-specific default batch size.  Architecture says this is a
    # "mode-specific default in system_modes.json".
    # We treat default_min_length as the base_unit_count for the
    # shishi-odoshi formula since it's the mode-specific numeric default.
    # A dedicated base_unit_count field can be added later if needed.
    base_unit_count = (mode_config or {}).get("base_unit_count",
                       (mode_config or {}).get("default_min_length", 100))

    fill_threshold = base_unit_count * (1.0 - slider_value)
    # Ensure threshold is at least 1 to avoid immediate trigger
    fill_threshold = max(1, int(fill_threshold))

    # Count pending records for this mission
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM ingest_records "
        "WHERE mission_id = ? AND status = 'pending'",
        (mission_id,),
    ).fetchone()
    pending_count = row["cnt"]

    if pending_count >= fill_threshold:
        # Promote all pending to received
        cursor = conn.execute(
            "SELECT ingest_id FROM ingest_records "
            "WHERE mission_id = ? AND status = 'pending'",
            (mission_id,),
        )
        promoted_ids = [r["ingest_id"] for r in cursor.fetchall()]

        conn.execute(
            "UPDATE ingest_records SET status = 'received' "
            "WHERE mission_id = ? AND status = 'pending'",
            (mission_id,),
        )

        _log(conn, mission_id, "stage_complete",
             f"Shishi-odoshi threshold reached ({pending_count}/{fill_threshold}). "
             f"Promoted {len(promoted_ids)} records to 'received'.")

        return promoted_ids

    return []


# ──────────────────────────────────────────────────────────────
# Batch ingest helper
# ──────────────────────────────────────────────────────────────

def ingest_batch(
    mission_id: str,
    records: list[dict],
    db_path: Path | None = None,
) -> list[dict]:
    """Ingest multiple records in sequence.

    Each dict in *records* must have keys: source, format, raw_content.
    Returns a list of result dicts (one per input record).
    """
    results = []
    for rec in records:
        result = ingest_record(
            mission_id=mission_id,
            source=rec.get("source", ""),
            format=rec.get("format", ""),
            raw_content=rec.get("raw_content", ""),
            db_path=db_path,
        )
        results.append(result)
    return results


# ──────────────────────────────────────────────────────────────
# Query helpers
# ──────────────────────────────────────────────────────────────

def get_received_records(
    mission_id: str,
    db_path: Path | None = None,
) -> list[dict]:
    """Return all ingest records with status 'received' for a mission."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            "SELECT ingest_id, mission_id, source, format, raw_content, "
            "       timestamp, status "
            "FROM ingest_records "
            "WHERE mission_id = ? AND status = 'received' "
            "ORDER BY timestamp",
            (mission_id,),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_pending_count(
    mission_id: str,
    db_path: Path | None = None,
) -> int:
    """Return the number of pending ingest records for a mission."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM ingest_records "
            "WHERE mission_id = ? AND status = 'pending'",
            (mission_id,),
        ).fetchone()
        return row["cnt"]
    finally:
        conn.close()


def ingest_from_urls(
    mission_id: str,
    urls: list[str],
    db_path: Path | None = None,
) -> list[dict]:
    """Scrape URLs, convert to clean text via MarkItDown, and ingest them.

    If a URL is unreachable or empty, logs the failure and skips it.
    """
    import tempfile
    import requests
    from bs4 import BeautifulSoup
    from markitdown import MarkItDown

    results = []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/115.0.0.0 Safari/537.36"
        )
    }

    md = MarkItDown()

    for url in urls:
        try:
            # Fetch content
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            html = resp.text

            if not html.strip():
                raise ValueError("Empty response content")

            # Clean HTML with BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            cleaned_html = str(soup)

            # Convert to Markdown via MarkItDown using a temp file
            with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
                f.write(cleaned_html)
                temp_path = Path(f.name)

            try:
                converted = md.convert(str(temp_path))
                text_content = converted.text_content
            finally:
                temp_path.unlink(missing_ok=True)

            if not text_content.strip():
                raise ValueError("Converted text content is empty")

            # Ingest the clean text
            record = ingest_record(
                mission_id=mission_id,
                source=url,
                format="markdown",
                raw_content=text_content,
                db_path=db_path,
            )
            if "error" not in record:
                results.append(record)
            else:
                # Log ingestion error
                conn = get_connection(db_path)
                try:
                    _log(conn, mission_id, "ai_error", f"Failed to ingest URL {url}: {record['error']}", "ingest_error")
                    conn.commit()
                finally:
                    conn.close()

        except Exception as exc:
            # Log failure, skip, do not halt
            conn = get_connection(db_path)
            try:
                _log(conn, mission_id, "ai_error", f"Failed to scrape URL {url}: {exc}", "scrape_error")
                conn.commit()
            finally:
                conn.close()

    return results
