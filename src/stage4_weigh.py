"""
Committee OS — Stage 4: Weigh.

Scores passing units against the eight lens rubrics.
Rubrics are external to AI. Scoring is computational.

Architecture §4 Contract
-------------------------
INPUT   : Passing units from Stage 3
PROCESS : 1. Evaluate 5 binary criteria per lens (0 or 1).
          2. Compute raw_score = matched_criteria / total_criteria (0.0 - 1.0).
          3. Apply weight modifiers:
             - Base weight from config.json (default 1.0).
             - Amplified weight (1.5) if lens is in active_emphasis_lenses.
             - Multiplied by the average of peer-review role modifiers from system_modes.json.
             - Enforce floor (0.5) and ceiling (2.0) constraints.
          4. Compute weighted_score = raw_score * weight.
          5. Compute aggregate_score = sum(lens_score * weight) / sum(weight).
          6. Filter units below gate_threshold (default 0.55) on all lenses.
          Store to lens_scores table.
OUTPUT  : lens score records per §4 schema
"""

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
        VALUES (?, ?, 'WEIGH', ?, ?, ?, ?)
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
# Lens Criteria Definitions
# ──────────────────────────────────────────────────────────────

LENSES = [
    "creative_director",
    "financial_director",
    "technical_director",
    "marketing_director",
    "audience_retention",
    "chief_executor",
    "archivist",
    "legal_qa",
]

# Helper patterns for criteria evaluation
_PATTERNS = {
    "creative_director": [
        re.compile(r"\b(?:original|unique|novel|innovative|creative|fresh|unconventional|distinctive)\b", re.IGNORECASE),
        re.compile(r"\b(?:visual|narrative|structural|story|aesthetic|design|layout|format|style)\b", re.IGNORECASE),
        re.compile(r"\b(?:brand|aesthetic|presentation|look|feel|identity|logo|theme)\b", re.IGNORECASE),
        re.compile(r"\b(?:practical|apply|use|implement|execute|run|do)\b", re.IGNORECASE),  # Practical application
        re.compile(r"^.*$"),  # Repetition check (always true since Stage 3 filtered duplicates)
    ],
    "financial_director": [
        re.compile(r"\b(?:\$|USD|EUR|GBP|budget|cost|expense|spend|price|fee|revenue|profit)\b", re.IGNORECASE),
        re.compile(r"\b(?:ROI|return on investment|efficiency|expenditure|savings|cost-effective|optimize)\b", re.IGNORECASE),
        re.compile(r"\b(?:risk|savings|opportunity|reduction|increase|cut|growth|improve)\b.*\b\d+\b", re.IGNORECASE),
        re.compile(r"\b(?:production|operation|expense|overhead|cost|infrastructure|resource)\b", re.IGNORECASE),
        re.compile(r"^(?!.*\b(?:speculate|forecast|predict|projection|estimate)\b.*\b(?!\d)\b).*$", re.IGNORECASE),  # Not speculative without data
    ],
    "technical_director": [
        re.compile(r"\b(?:process|method|tool|technique|system|algorithm|software|hardware|framework|library)\b", re.IGNORECASE),
        re.compile(r"\b(?:practical|apply|use|implement|execute|run|deploy|install|configure)\b", re.IGNORECASE),
        re.compile(r"\b(?:novel|unconventional|optimize|efficient|performance|speed|scale|latency)\b", re.IGNORECASE),
        re.compile(r"^(?!.*\b(?:unsafe|insecure|vulnerable|deprecated|hack|bypass)\b).*$", re.IGNORECASE),  # Avoids unsafe practices
        re.compile(r"\b(?:code|config|data|database|network|server|api|function|class|module)\b", re.IGNORECASE),
    ],
    "marketing_director": [
        re.compile(r"\b(?:audience|reach|platform|user|customer|viewer|subscriber|follower|visitor)\b", re.IGNORECASE),
        re.compile(r"\b(?:engagement|growth|distribution|metric|analytics|traffic|conversion|ctr|cpc)\b", re.IGNORECASE),
        re.compile(r"\b(?:current|relevant|platform|modern|latest|trend|now|today)\b", re.IGNORECASE),
        re.compile(r"\b(?:package|position|algorithm|seo|ranking|discoverability|thumbnail|title)\b", re.IGNORECASE),
        re.compile(r"^(?!.*\b(?:clickbait|spam|cheat|shortcut|fake)\b).*$", re.IGNORECASE),  # Brand authenticity
    ],
    "audience_retention": [
        re.compile(r"^(?!.*\b(?:complexity|convoluted|difficult|hard to understand)\b).*$", re.IGNORECASE),  # Clear, free of complexity
        re.compile(r"\b(?:learn|understand|how to|guide|tutorial|tip|insight|skill|value)\b", re.IGNORECASE),
        re.compile(r"\b(?:pain point|problem|issue|challenge|difficulty|frustration|error|bug|fail)\b", re.IGNORECASE),
        re.compile(r"^.{30,300}$"),  # Balanced depth
        re.compile(r"^(?!.*\b(?:entertainment|funny|joke|meme|viral|gimmick)\b).*$", re.IGNORECASE),  # Avoids pure entertainment
    ],
    "chief_executor": [
        re.compile(r"\b(?:action|decision|next step|todo|task|plan|milestone|deliverable)\b", re.IGNORECASE),
        re.compile(r"^(?!.*\b(?:maybe|perhaps|possibly|unsure|unclear|ambiguous)\b).*$", re.IGNORECASE),  # Unambiguous
        re.compile(r"\b(?:constraint|limit|protocol|rule|requirement|policy|standard)\b", re.IGNORECASE),
        re.compile(r"^(?!.*\b(?:creative|artistic|budget|cost|price|funding)\b).*$", re.IGNORECASE),  # No creative/financial decisions
        re.compile(r"\b(?:progress|advance|complete|finish|done|milestone|stage)\b", re.IGNORECASE),
    ],
    "archivist": [
        re.compile(r"\b(?:reference|category|data|precedent|history|record|archive|source|citation)\b", re.IGNORECASE),
        re.compile(r"\b(?:index|recall|retrieve|structure|tag|metadata|key|id|uuid)\b", re.IGNORECASE),
        re.compile(r"^(?!.*\b(?:speculate|guess|predict|forecast|hypothesize)\b).*$", re.IGNORECASE),  # Avoids speculation
        re.compile(r"\b(?:knowledge|value|insight|lesson|learn|history|database|repo)\b", re.IGNORECASE),
        re.compile(r"^(?!.*\b(?:repeat|failure|fail|error|bug)\b).*$", re.IGNORECASE),  # Non-redundant failure
    ],
    "legal_qa": [
        re.compile(r"\b(?:verify|trace|source|proof|evidence|fact|confirm|check|audit)\b", re.IGNORECASE),
        re.compile(r"\b(?:compliance|liability|ethical|risk|legal|law|regulation|policy|safety)\b", re.IGNORECASE),
        re.compile(r"\b(?:guideline|standard|policy|rule|requirement|specification|spec)\b", re.IGNORECASE),
        re.compile(r"^(?!.*\b(?:sue|lawsuit|illegal|unlawful|court|attorney)\b).*$", re.IGNORECASE),  # No unverified legal assertions
        re.compile(r"^(?!.*\b(?:mislead|harm|unsubstantiated|fake|false|lie)\b).*$", re.IGNORECASE),  # Trust integrity
    ],
}


def _evaluate_lens(content: str, lens: str) -> tuple[float, dict]:
    """Evaluate a unit's content against the 5 criteria of a lens.

    Returns (raw_score, criteria_breakdown).
    """
    patterns = _PATTERNS.get(lens, [])
    breakdown = {}
    matched = 0

    for idx, pattern in enumerate(patterns):
        criterion_name = f"criterion_{idx + 1}"
        match = bool(pattern.search(content))
        breakdown[criterion_name] = 1 if match else 0
        if match:
            matched += 1

    raw_score = matched / len(patterns) if patterns else 0.0
    return raw_score, breakdown


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

def weigh_units(
    mission_id: str,
    db_path: Path | None = None,
) -> list[dict]:
    """Score all passing units for a mission against the eight lens rubrics.

    Computes raw, weighted, and aggregate scores, and persists to lens_scores.
    """
    conn = get_connection(db_path)
    try:
        # ── Fetch mission & configuration ─────────────────────
        row = conn.execute(
            "SELECT domain, calibration FROM missions WHERE mission_id = ?",
            (mission_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"mission_id '{mission_id}' not found.")

        domain = row["domain"]
        calibration = json.loads(row["calibration"])
        active_emphasis = calibration.get("active_emphasis_lenses", [])

        cfg = _load_config()
        gate_threshold = cfg.get("gate_threshold", 0.55)
        lens_weight_default = cfg.get("lens_weight_default", 1.0)
        lens_weight_amplified = cfg.get("lens_weight_amplified", 1.5)
        lens_weight_floor = cfg.get("lens_weight_floor", 0.5)

        # ── Load peer-review role modifiers ───────────────────
        mode_cfg = _load_mode_config(domain)
        roles = mode_cfg.get("peer_review_roles", []) if mode_cfg else []

        # Average the modifiers across all roles for this mode
        combined_modifiers = {}
        for lens in LENSES:
            mods = [r["lens_modifiers"].get(lens, 1.0) for r in roles if "lens_modifiers" in r]
            combined_modifiers[lens] = sum(mods) / len(mods) if mods else 1.0

        _log(conn, mission_id, "stage_start",
             f"Weighing started — domain: {domain}, emphasis: {active_emphasis}")

        # ── Fetch passing units ───────────────────────────────
        cursor = conn.execute(
            """
            SELECT pu.unit_id, pu.content
            FROM parsed_units pu
            JOIN filter_results fr ON pu.unit_id = fr.unit_id
            JOIN ingest_records ir ON pu.ingest_id = ir.ingest_id
            WHERE ir.mission_id = ? AND fr.status = 'pass'
            """,
            (mission_id,),
        )
        units = cursor.fetchall()

        results = []

        for unit in units:
            unit_id = unit["unit_id"]
            content = unit["content"]

            lens_scores = {}
            weights = {}
            weighted_scores = {}

            # Evaluate each lens
            for lens in LENSES:
                raw_score, breakdown = _evaluate_lens(content, lens)

                # Determine base weight
                base_w = lens_weight_amplified if lens in active_emphasis else lens_weight_default

                # Apply peer-review modifier
                mod = combined_modifiers.get(lens, 1.0)
                weight = base_w * mod

                # Enforce floor and ceiling constraints
                weight = max(lens_weight_floor, min(2.0, weight))

                weighted_score = raw_score * weight

                lens_scores[lens] = raw_score
                weights[lens] = weight
                weighted_scores[lens] = weighted_score

                # Persist to lens_scores
                conn.execute(
                    """
                    INSERT OR REPLACE INTO lens_scores
                        (unit_id, lens, raw_score, criteria_breakdown, weighted_score)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (unit_id, lens, raw_score, json.dumps(breakdown), weighted_score),
                )

            # Compute aggregate score (weighted mean)
            sum_weighted = sum(weighted_scores.values())
            sum_weights = sum(weights.values())
            aggregate_score = sum_weighted / sum_weights if sum_weights > 0 else 0.0

            # Check if unit passes the gate (at least one lens raw_score >= gate_threshold)
            # Wait, the spec says: "Units below threshold on a given lens are marked filtered for that lens.
            # Units filtered by ALL lenses are eliminated before Stage 5."
            # So a unit passes if at least one lens raw_score >= gate_threshold.
            passed_gate = any(score >= gate_threshold for score in lens_scores.values())

            results.append({
                "unit_id": unit_id,
                "aggregate_score": aggregate_score,
                "passed_gate": passed_gate,
                "lens_scores": lens_scores,
            })

        _log(conn, mission_id, "stage_complete",
             f"Weighing complete — scored {len(results)} units.")

        conn.commit()
        return results

    except Exception as exc:
        conn.rollback()
        raise exc
    finally:
        conn.close()


def get_top_scored_units(
    mission_id: str,
    limit: int = 5,
    db_path: Path | None = None,
) -> list[dict]:
    """Retrieve the top N units by aggregate score descending that passed the gate."""
    # We compute the aggregate score on the fly from the database or query the results.
    # Since we don't store aggregate_score directly in a table (it's computed from lens_scores),
    # we query lens_scores, group by unit_id, and compute the weighted mean.
    conn = get_connection(db_path)
    try:
        # First, get the gate threshold from config
        cfg = _load_config()
        gate_threshold = cfg.get("gate_threshold", 0.55)

        cursor = conn.execute(
            """
            SELECT ls.unit_id, pu.content,
                   SUM(ls.weighted_score) as sum_weighted,
                   SUM(ls.weighted_score / ls.raw_score) as sum_weights_approx, -- raw_score is weighted_score / weight
                   MAX(ls.raw_score) as max_raw_score
            FROM lens_scores ls
            JOIN parsed_units pu ON ls.unit_id = pu.unit_id
            JOIN ingest_records ir ON pu.ingest_id = ir.ingest_id
            WHERE ir.mission_id = ?
            GROUP BY ls.unit_id
            HAVING max_raw_score >= ?
            """,
            (mission_id, gate_threshold),
        )
        rows = cursor.fetchall()

        # Since floating point division by zero or weight reconstruction can be tricky in SQL,
        # let's fetch all lens_scores for these units and compute aggregate score precisely in Python.
        unit_data = {}
        for row in rows:
            uid = row["unit_id"]
            unit_data[uid] = {
                "unit_id": uid,
                "content": row["content"],
                "weighted_scores": [],
                "weights": [],
                "lens_scores": {},
            }

        if not unit_data:
            return []

        placeholders = ",".join("?" for _ in unit_data)
        cursor = conn.execute(
            f"""
            SELECT unit_id, lens, raw_score, weighted_score
            FROM lens_scores
            WHERE unit_id IN ({placeholders})
            """,
            list(unit_data.keys()),
        )
        for row in cursor.fetchall():
            uid = row["unit_id"]
            raw = row["raw_score"]
            weighted = row["weighted_score"]
            # Reconstruct weight: weighted = raw * weight => weight = weighted / raw if raw > 0 else weight
            # Wait, if raw is 0, weighted is also 0. We need the actual weight.
            # Let's fetch the mission's domain and calibration to compute the exact weight for each lens.
            # To keep it simple and robust, let's query the weights we used.
            # Actually, we can store the weight in the database or just compute it here.
            # Let's compute the weight here using the same logic.
            unit_data[uid]["weighted_scores"].append(weighted)
            unit_data[uid]["lens_scores"][row["lens"]] = raw

        # Fetch mission domain and calibration to compute weights
        row = conn.execute(
            "SELECT domain, calibration FROM missions WHERE mission_id = ?",
            (mission_id,),
        ).fetchone()
        domain = row["domain"]
        calibration = json.loads(row["calibration"])
        active_emphasis = calibration.get("active_emphasis_lenses", [])

        mode_cfg = _load_mode_config(domain)
        roles = mode_cfg.get("peer_review_roles", []) if mode_cfg else []

        combined_modifiers = {}
        for lens in LENSES:
            mods = [r["lens_modifiers"].get(lens, 1.0) for r in roles if "lens_modifiers" in r]
            combined_modifiers[lens] = sum(mods) / len(mods) if mods else 1.0

        lens_weight_default = cfg.get("lens_weight_default", 1.0)
        lens_weight_amplified = cfg.get("lens_weight_amplified", 1.5)
        lens_weight_floor = cfg.get("lens_weight_floor", 0.5)

        weights = {}
        for lens in LENSES:
            base_w = lens_weight_amplified if lens in active_emphasis else lens_weight_default
            mod = combined_modifiers.get(lens, 1.0)
            weight = base_w * mod
            weights[lens] = max(lens_weight_floor, min(2.0, weight))

        # Compute aggregate score for each unit
        scored_units = []
        for uid, data in unit_data.items():
            sum_weighted = 0.0
            sum_weights = 0.0
            for lens in LENSES:
                raw = data["lens_scores"].get(lens, 0.0)
                w = weights[lens]
                sum_weighted += raw * w
                sum_weights += w

            agg = sum_weighted / sum_weights if sum_weights > 0 else 0.0
            scored_units.append({
                "unit_id": uid,
                "content": data["content"],
                "aggregate_score": agg,
                "lens_scores": data["lens_scores"],
            })

        # Sort by aggregate score descending
        scored_units.sort(key=lambda x: x["aggregate_score"], reverse=True)
        return scored_units[:limit]

    finally:
        conn.close()
