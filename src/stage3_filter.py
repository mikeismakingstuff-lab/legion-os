"""
Committee OS — Stage 3: Filter.

Removes units that are structurally disqualified.
Not judgment — elimination of noise by explicit rule.

Architecture §3 Contract
-------------------------
INPUT   : Parsed units
PROCESS : Apply 4 filter rules in sequence:
          1. Minimum content length: user-defined at runtime (calibration or config).
             Pipeline will not proceed past Stage 3 without a value set — no silent default.
          2. Duplicate detection (exact + near-duplicate by hash).
          3. Format-only content (whitespace, punctuation-only, markup artifacts).
          4. Domain-specific disqualification rules (maps to volume/quality slider).
          Store to filter_results table.
OUTPUT  : filter result records per §3 schema
FAILURE : If filter logic errors → unit passes. Err on inclusion, not exclusion.
"""

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.db import get_connection

# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config.json"
_SYSTEM_MODES_PATH = _PROJECT_ROOT / "system_modes.json"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(conn, mission_id: str, event: str, detail: str,
         error_code: str | None = None) -> None:
    conn.execute(
        """
        INSERT INTO pipeline_log
            (log_id, mission_id, stage, event, detail, timestamp, error_code)
        VALUES (?, ?, 'FILTER', ?, ?, ?, ?)
        """,
        (str(uuid.uuid4()), mission_id, event, detail, _iso_now(), error_code),
    )


def _load_config() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_mode_config(domain: str) -> dict | None:
    with open(_SYSTEM_MODES_PATH, "r", encoding="utf-8") as f:
        modes = json.load(f)
    for m in modes:
        if m["mode_id"] == domain:
            return m
    return None


# ──────────────────────────────────────────────────────────────
# Rule 2: Near-duplicate hash helper
# ──────────────────────────────────────────────────────────────

def _compute_near_dup_hash(text: str) -> str:
    """Compute a normalized hash for near-duplicate detection.

    Normalizes text by lowercasing, removing all non-alphanumeric characters,
    and collapsing whitespace.
    """
    normalized = re.sub(r"[^a-z0-9]", "", text.lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ──────────────────────────────────────────────────────────────
# Rule 3: Format-only content checker
# ──────────────────────────────────────────────────────────────

# Punctuation and whitespace only
_FORMAT_ONLY_PATTERN = re.compile(r"^[ \t\r\n\s!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_\`{|}~]*$")


def _is_format_only(text: str) -> bool:
    return bool(_FORMAT_ONLY_PATTERN.match(text))


# ──────────────────────────────────────────────────────────────
# Rule 4: Domain-specific disqualification rules
# ──────────────────────────────────────────────────────────────

# Domain rules map to the volume/quality slider value (0.0 to 1.0)
# Slider >= 0.5 triggers standard domain-specific noise filtering.
# Slider >= 0.8 triggers aggressive domain-specific noise filtering.
# Slider < 0.5 runs in high-volume mode (no domain-specific filtering).

_DOMAIN_FILTERS = {
    "educational_academy": {
        "standard": re.compile(r"(?:\?{3,}|!{3,})"),  # Malformed strings (e.g. ??? or !!!)
        "aggressive": re.compile(r"(?:\?{2,}|!{2,}|unaligned|off-curriculum)"),
    },
    "content_syndicate": {
        "standard": re.compile(r"\b(?:stale|deprecated|outdated)\b", re.IGNORECASE),
        "aggressive": re.compile(r"\b(?:stale|deprecated|outdated|clickbait|spam|ad)\b", re.IGNORECASE),
    },
    "secops_triager": {
        "standard": re.compile(r"\b(?:DEBUG|INFO|localhost|127\.0\.0\.1)\b"),
        "aggressive": re.compile(r"\b(?:DEBUG|INFO|TRACE|localhost|127\.0\.0\.1|test-event)\b"),
    },
    "code_guard": {
        "standard": re.compile(r"^\s*(?://|#|/\*|\*)\s*"),  # Documentation/comment lines
        "aggressive": re.compile(r"^\s*(?://|#|/\*|\*|\bdocs?:\b)\s*", re.IGNORECASE),
    },
    "video_narrative_engine": {
        "standard": re.compile(r"^#\w+$"),  # Single hashtag lines
        "aggressive": re.compile(r"(?:^#\w+$|\b(?:like|subscribe|share|comment below)\b)", re.IGNORECASE),
    },
    "customer_voc_synthesizer": {
        "standard": re.compile(r"\b(?:resolved|closed|fixed)\b", re.IGNORECASE),
        "aggressive": re.compile(r"\b(?:resolved|closed|fixed|thank you|thanks|hello|hi)\b", re.IGNORECASE),
    },
    "product_listing_machine": {
        "standard": re.compile(r"\b(?:N/A|null|none)\b", re.IGNORECASE),
        "aggressive": re.compile(r"\b(?:N/A|null|none|unknown value|placeholder)\b", re.IGNORECASE),
    },
    "real_estate_qualifier": {
        "standard": re.compile(r"\b(?:no price|missing data)\b", re.IGNORECASE),
        "aggressive": re.compile(r"\b(?:no price|missing data|unvalued|placeholder)\b", re.IGNORECASE),
    },
    "patch_guard": {
        "standard": re.compile(r"\b(?:superseded|obsolete)\b", re.IGNORECASE),
        "aggressive": re.compile(r"\b(?:superseded|obsolete|not affected|ignore)\b", re.IGNORECASE),
    },
    "digital_archival_processor": {
        "standard": re.compile(r"[^\x20-\x7E\s]{3,}"),  # Too many non-printable characters
        "aggressive": re.compile(r"[^\x20-\x7E\s]{2,}|(?:corrupt|garbage)"),
    },
    "network_flow_hunter": {
        "standard": re.compile(r"\b(?:google\.com|amazonaws\.com|cloudflare\.com)\b", re.IGNORECASE),
        "aggressive": re.compile(r"\b(?:google\.com|amazonaws\.com|cloudflare\.com|localhost|127\.0\.0\.1)\b", re.IGNORECASE),
    },
    "market_sentiment_aggregator": {
        "standard": re.compile(r"\b(?:synergy|paradigm shift|world-class)\b", re.IGNORECASE),
        "aggressive": re.compile(r"\b(?:synergy|paradigm shift|world-class|game-changer|disruptive)\b", re.IGNORECASE),
    },
    "telemetry_diagnostic_loop": {
        "standard": re.compile(r"\b(?:normal|nominal|status OK)\b", re.IGNORECASE),
        "aggressive": re.compile(r"\b(?:normal|nominal|status OK|baseline|healthy)\b", re.IGNORECASE),
    },
    "lit_review_examiner": {
        "standard": re.compile(r"\b(?:blog post|opinion|editorial)\b", re.IGNORECASE),
        "aggressive": re.compile(r"\b(?:blog post|opinion|editorial|retracted|preprint)\b", re.IGNORECASE),
    },
}


def _is_domain_disqualified(text: str, domain: str, slider: float) -> bool:
    if slider < 0.5:
        return False

    filters = _DOMAIN_FILTERS.get(domain)
    if not filters:
        return False

    if slider >= 0.8:
        pattern = filters["aggressive"]
    else:
        pattern = filters["standard"]

    return bool(pattern.search(text))


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

def filter_units(
    mission_id: str,
    db_path: Path | None = None,
) -> list[dict]:
    """Filter all parsed units for a mission.

    Applies the 4 filter rules in sequence.
    If filter logic errors, the unit passes (err on inclusion).

    Returns a list of filter result dicts.
    """
    conn = get_connection(db_path)
    try:
        # ── Fetch mission details ─────────────────────────────
        row = conn.execute(
            "SELECT domain, calibration FROM missions WHERE mission_id = ?",
            (mission_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"mission_id '{mission_id}' not found.")

        domain = row["domain"]
        calibration = json.loads(row["calibration"])
        slider = calibration.get("volume_quality_slider", 0.5)

        # ── Determine min content length ──────────────────────
        # 1. Check calibration
        min_len = calibration.get("min_content_length")
        if min_len is None:
            # 2. Check config.json
            cfg = _load_config()
            cfg_min = cfg.get("parse_min_length")
            if isinstance(cfg_min, int):
                min_len = cfg_min
            elif cfg_min == "user_defined":
                # 3. Check system_modes.json default
                mode_cfg = _load_mode_config(domain)
                if mode_cfg:
                    min_len = mode_cfg.get("default_min_length")

        if min_len is None or not isinstance(min_len, int):
            # Pipeline will not proceed past Stage 3 without a value set
            raise ValueError(
                f"Minimum content length not set for mission '{mission_id}'. "
                "No silent default allowed."
            )

        _log(conn, mission_id, "stage_start",
             f"Filtering started — domain: {domain}, min_len: {min_len}, slider: {slider}")

        # ── Fetch parsed units ────────────────────────────────
        cursor = conn.execute(
            """
            SELECT pu.unit_id, pu.content, pu.character_count
            FROM parsed_units pu
            JOIN ingest_records ir ON pu.ingest_id = ir.ingest_id
            WHERE ir.mission_id = ?
            """,
            (mission_id,),
        )
        units = cursor.fetchall()

        results = []
        seen_exact = set()
        seen_near_hashes = set()

        for unit in units:
            unit_id = unit["unit_id"]
            content = unit["content"]
            char_count = unit["character_count"]

            status = "pass"
            fail_reason = None

            try:
                # Rule 1: Minimum content length
                if char_count < min_len:
                    status = "fail"
                    fail_reason = f"Length {char_count} below minimum {min_len}"

                # Rule 2: Duplicate detection
                elif content in seen_exact:
                    status = "fail"
                    fail_reason = "Exact duplicate"
                else:
                    near_hash = _compute_near_dup_hash(content)
                    if near_hash in seen_near_hashes:
                        status = "fail"
                        fail_reason = "Near-duplicate by hash"
                    else:
                        # Rule 3: Format-only content
                        if _is_format_only(content):
                            status = "fail"
                            fail_reason = "Format-only content"

                        # Rule 4: Domain-specific disqualification
                        elif _is_domain_disqualified(content, domain, slider):
                            status = "fail"
                            fail_reason = f"Domain-specific noise ({domain})"

                # If it passed all rules, record it as seen
                if status == "pass":
                    seen_exact.add(content)
                    seen_near_hashes.add(_compute_near_dup_hash(content))

            except Exception as rule_exc:
                # FAILURE: If filter logic errors → unit passes. Err on inclusion.
                status = "pass"
                fail_reason = None

            # Persist to filter_results
            conn.execute(
                """
                INSERT OR REPLACE INTO filter_results (unit_id, status, fail_reason)
                VALUES (?, ?, ?)
                """,
                (unit_id, status, fail_reason),
            )

            # Log unit status
            log_event = "unit_pass" if status == "pass" else "unit_fail"
            conn.execute(
                """
                INSERT INTO pipeline_log
                    (log_id, mission_id, stage, event, detail, timestamp, error_code)
                VALUES (?, ?, 'FILTER', ?, ?, ?, NULL)
                """,
                (str(uuid.uuid4()), mission_id, log_event,
                 f"Unit {unit_id}: {status}" + (f" ({fail_reason})" if fail_reason else ""),
                 _iso_now()),
            )

            results.append({
                "unit_id": unit_id,
                "status": status,
                "fail_reason": fail_reason,
            })

        _log(conn, mission_id, "stage_complete",
             f"Filtering complete — processed {len(results)} units. "
             f"Passed: {sum(1 for r in results if r['status'] == 'pass')}, "
             f"Failed: {sum(1 for r in results if r['status'] == 'fail')}")

        conn.commit()
        return results

    except Exception as exc:
        conn.rollback()
        # If the entire stage fails, we must log it and re-raise or return error
        raise exc
    finally:
        conn.close()


def get_filtered_units(
    mission_id: str,
    db_path: Path | None = None,
) -> list[dict]:
    """Retrieve all passing units for a mission from the database."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT pu.unit_id, pu.content, pu.character_count, pu.type
            FROM parsed_units pu
            JOIN filter_results fr ON pu.unit_id = fr.unit_id
            JOIN ingest_records ir ON pu.ingest_id = ir.ingest_id
            WHERE ir.mission_id = ? AND fr.status = 'pass'
            ORDER BY pu.unit_id
            """,
            (mission_id,),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()
