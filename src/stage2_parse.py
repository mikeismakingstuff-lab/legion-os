"""
Committee OS — Stage 2: Parse.

Transforms raw content into structured, queryable units.
No judgment.  No interpretation.  Parser has no knowledge of mission context.

Architecture §2 Contract
-------------------------
INPUT   : ingest_records with status "received"
PROCESS : Extract discrete units (sentences, claims, data points) by rule.
          Tag by structural type: fact | figure | claim | instruction | unknown.
          Strip formatting artifacts.
          Store to parsed_units table.
OUTPUT  : parsed unit records per §2 schema
FAILURE : Units that cannot be classified → tag "unknown", pass forward.
          Do not discard.  Do not hallucinate classification.
"""

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.db import get_connection

# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(conn, mission_id: str, event: str, detail: str,
         error_code: str | None = None) -> None:
    conn.execute(
        """
        INSERT INTO pipeline_log
            (log_id, mission_id, stage, event, detail, timestamp, error_code)
        VALUES (?, ?, 'PARSE', ?, ?, ?, ?)
        """,
        (str(uuid.uuid4()), mission_id, event, detail, _iso_now(), error_code),
    )


# ──────────────────────────────────────────────────────────────
# Formatting artifact removal
# ──────────────────────────────────────────────────────────────

# Patterns for common formatting artifacts to strip
_STRIP_PATTERNS = [
    (re.compile(r"<[^>]+>"), ""),                          # HTML tags
    (re.compile(r"\[/?[A-Z]+\]"), ""),                     # BBCode-style tags
    (re.compile(r"&[a-zA-Z]+;|&#\d+;"), ""),               # HTML entities
    (re.compile(r"^\s*[-*•]\s+", re.MULTILINE), ""),       # List bullets
    (re.compile(r"^\s*#+\s+", re.MULTILINE), ""),          # Markdown headings
    (re.compile(r"\*{1,2}([^*]+)\*{1,2}"), r"\1"),         # Bold/italic markers
    (re.compile(r"_{1,2}([^_]+)_{1,2}"), r"\1"),           # Underscore emphasis
    (re.compile(r"`([^`]+)`"), r"\1"),                      # Inline code backticks
    (re.compile(r"\r\n"), "\n"),                            # Normalize line endings
    (re.compile(r"[ \t]+"), " "),                           # Collapse whitespace
]


def _strip_formatting(text: str) -> str:
    """Remove formatting artifacts from text.  Pure rule-based."""
    result = text
    for pattern, replacement in _STRIP_PATTERNS:
        result = pattern.sub(replacement, result)
    return result.strip()


# ──────────────────────────────────────────────────────────────
# Unit extraction — sentence splitting by rule
# ──────────────────────────────────────────────────────────────

# Sentence boundary: period/exclamation/question followed by whitespace
# or end of string, with common abbreviation guards.
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "ave",
    "vs", "etc", "approx", "dept", "est", "inc", "ltd", "co",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep",
    "oct", "nov", "dec", "fig", "eq", "vol", "no", "pp",
    "e.g", "i.e", "cf",
}

# Split on sentence-ending punctuation followed by space + uppercase or EOL
_SENTENCE_SPLIT = re.compile(
    r'(?<=[.!?])\s+(?=[A-Z"\'])|(?<=[.!?])\s*\n'
)


def _split_into_units(text: str) -> list[str]:
    """Split text into sentence-level units by rule.

    Falls back to paragraph splitting if no sentence boundaries are found.
    Single-line inputs return as a single unit.
    """
    # First, split by double newlines (paragraphs)
    paragraphs = re.split(r"\n\s*\n", text.strip())

    units = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # Try sentence splitting within each paragraph
        sentences = _SENTENCE_SPLIT.split(para)
        for sent in sentences:
            sent = sent.strip()
            if sent:
                units.append(sent)

    # If we got nothing, return the original as a single unit
    if not units and text.strip():
        units = [text.strip()]

    return units


# ──────────────────────────────────────────────────────────────
# Structural type classification — rule-based, no inference
# ──────────────────────────────────────────────────────────────

# Figure patterns: numbers, percentages, currencies, measurements
_FIGURE_PATTERN = re.compile(
    r"(?:"
    r"\$[\d,]+(?:\.\d+)?[BMKbmk]?"       # Currency: $1,234.56M
    r"|[\d,]+(?:\.\d+)?\s*%"              # Percentage: 45.2%
    r"|[\d,]+(?:\.\d+)?\s*(?:ms|μs|ns|s|min|hr|hrs|MB|GB|TB|KB|MHz|GHz|kg|lb|lbs|oz|mg|ml|cm|mm|km|mi|ft|in|m²|ft²)"  # Measurements
    r"|\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b" # Large numbers: 1,234,567
    r")"
)

# Claim indicators: opinion/assertion language
_CLAIM_INDICATORS = re.compile(
    r"\b(?:"
    r"(?:it\s+)?(?:is|are|was|were)\s+(?:the\s+)?(?:best|worst|most|least|better|worse)"
    r"|should\s+(?:be|have|not)"
    r"|must\s+(?:be|have|not)"
    r"|(?:we|they|it)\s+(?:need|believe|suggest|argue|propose|recommend|claim)"
    r"|according\s+to"
    r"|studies?\s+(?:show|suggest|indicate|demonstrate|reveal)"
    r"|research\s+(?:shows?|suggests?|indicates?)"
    r"|evidence\s+(?:shows?|suggests?|indicates?)"
    r"|it\s+(?:appears?|seems?)\s+(?:that|to)"
    r"|(?:clearly|obviously|undoubtedly|arguably)"
    r")\b",
    re.IGNORECASE,
)

# Instruction indicators: imperative / directive language
_INSTRUCTION_INDICATORS = re.compile(
    r"(?:"
    r"^\s*(?:do\s+not|don't|never|always|ensure|verify|check|run|execute|install|configure|set|create|delete|remove|add|update|use|avoid|note|remember|warning|caution|important)\b"
    r"|^\s*\d+[.)]\s+"                     # Numbered steps: 1. 2) etc.
    r"|^\s*step\s+\d+"                     # "Step 1", "Step 2"
    r")",
    re.IGNORECASE | re.MULTILINE,
)

# Fact indicators: definitive statements with specific data
_FACT_INDICATORS = re.compile(
    r"\b(?:"
    r"(?:founded|established|created|released|launched|published)\s+(?:in|on)\s+\d"
    r"|(?:located|based|headquartered)\s+(?:in|at)\b"
    r"|(?:is|are|was|were)\s+(?:a|an|the)\s+[a-z]"
    r"|(?:consists?\s+of|comprises?|contains?|includes?)\b"
    r"|(?:invented|discovered|developed)\s+(?:by|in)\b"
    r"|(?:named\s+after|known\s+as|also\s+called)\b"
    r")",
    re.IGNORECASE,
)


def _classify_unit(text: str) -> str:
    """Classify a text unit into one of: fact, figure, claim, instruction, unknown.

    Classification is by rule only.  No inference.  No mission context.
    If no rule matches, the unit is tagged 'unknown' and passed forward.
    """
    # Priority order: instruction > figure > claim > fact > unknown
    # Instruction detection (imperative/procedural language)
    if _INSTRUCTION_INDICATORS.search(text):
        return "instruction"

    # Figure detection (contains significant numeric data)
    figure_matches = _FIGURE_PATTERN.findall(text)
    if len(figure_matches) >= 1:
        return "figure"

    # Claim detection (opinion/assertion language)
    if _CLAIM_INDICATORS.search(text):
        return "claim"

    # Fact detection (definitive statements)
    if _FACT_INDICATORS.search(text):
        return "fact"

    # Cannot classify → "unknown".  Do not discard.
    return "unknown"


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

def parse_ingest_record(
    ingest_id: str,
    mission_id: str,
    db_path: Path | None = None,
) -> list[dict]:
    """Parse a single ingest record into structured units.

    Reads the raw_content from ingest_records, splits into units,
    classifies each, strips formatting, and persists to parsed_units.

    Parameters
    ----------
    ingest_id  : the ingest record to parse
    mission_id : for logging (parser has no mission context for classification)
    db_path    : override for testing

    Returns
    -------
    List of parsed unit dicts, or a single-element list with an error dict.
    """
    conn = get_connection(db_path)
    try:
        # Fetch the ingest record
        row = conn.execute(
            "SELECT raw_content FROM ingest_records "
            "WHERE ingest_id = ? AND status = 'received'",
            (ingest_id,),
        ).fetchone()

        if row is None:
            return [{"error": f"ingest_id '{ingest_id}' not found or not 'received'."}]

        raw_content = row["raw_content"]

        _log(conn, mission_id, "stage_start",
             f"Parsing ingest_id: {ingest_id}")

        # Strip formatting artifacts
        cleaned = _strip_formatting(raw_content)

        # Split into discrete units
        raw_units = _split_into_units(cleaned)

        parsed_units = []
        for unit_text in raw_units:
            if not unit_text.strip():
                continue

            unit_id = str(uuid.uuid4())
            unit_type = _classify_unit(unit_text)
            character_count = len(unit_text)

            conn.execute(
                """
                INSERT INTO parsed_units
                    (unit_id, ingest_id, type, content, character_count, status)
                VALUES (?, ?, ?, ?, ?, 'parsed')
                """,
                (unit_id, ingest_id, unit_type, unit_text, character_count),
            )

            parsed_units.append({
                "unit_id": unit_id,
                "ingest_id": ingest_id,
                "type": unit_type,
                "content": unit_text,
                "character_count": character_count,
                "status": "parsed",
            })

        _log(conn, mission_id, "stage_complete",
             f"Parsed {len(parsed_units)} units from ingest_id: {ingest_id}")

        conn.commit()
        return parsed_units

    except Exception as exc:
        conn.rollback()
        return [{"error": f"Parse error: {exc}"}]
    finally:
        conn.close()


def parse_all_received(
    mission_id: str,
    db_path: Path | None = None,
) -> list[dict]:
    """Parse all 'received' ingest records for a mission.

    Returns a flat list of all parsed unit dicts.
    """
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            "SELECT ingest_id FROM ingest_records "
            "WHERE mission_id = ? AND status = 'received'",
            (mission_id,),
        )
        ingest_ids = [r["ingest_id"] for r in cursor.fetchall()]
    finally:
        conn.close()

    all_units = []
    for iid in ingest_ids:
        units = parse_ingest_record(iid, mission_id, db_path)
        all_units.extend(units)

    return all_units


def get_parsed_units(
    mission_id: str,
    db_path: Path | None = None,
) -> list[dict]:
    """Retrieve all parsed units for a mission from the database."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT pu.unit_id, pu.ingest_id, pu.type, pu.content,
                   pu.character_count, pu.status
            FROM parsed_units pu
            JOIN ingest_records ir ON pu.ingest_id = ir.ingest_id
            WHERE ir.mission_id = ?
            ORDER BY pu.unit_id
            """,
            (mission_id,),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()
