"""SQL-backed tools for the data-quality agent.

Three callables the agent loop will later expose as tools:

  * run_sql_query(query)   - run one arbitrary read-only SELECT
  * get_summary_stats()    - fixed set of headline aggregates
  * run_quality_checks()   - fixed battery of data-quality checks

Every function opens a FRESH connection using AGENT_DATABASE_URL (the SELECT-only
`app_readonly` role) and closes it before returning. DATABASE_URL (the owner role
used by the loader) is never touched here.

The single-SELECT guard in run_sql_query is defence-in-depth only: the database
role itself cannot write. It exists so obviously-wrong queries fail fast with a
clear message instead of hitting Postgres.
"""

from __future__ import annotations

import datetime
import decimal
import os
import re
from contextlib import contextmanager

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

load_dotenv()

MAX_ROWS = 500  # hard cap on rows returned by run_sql_query, so one query can't flood context


# --------------------------------------------------------------------------------------
# Connection handling
# --------------------------------------------------------------------------------------


def _agent_dsn() -> str:
    dsn = os.getenv("AGENT_DATABASE_URL")
    if not dsn:
        raise RuntimeError(
            "AGENT_DATABASE_URL is not set. It must point at the SELECT-only role "
            "(app_readonly). Do not fall back to DATABASE_URL here."
        )
    return dsn


@contextmanager
def _connect():
    """Fresh psycopg2 connection, forced read-only, always closed."""
    conn = psycopg2.connect(_agent_dsn())
    try:
        conn.set_session(readonly=True, autocommit=True)
        yield conn
    finally:
        conn.close()


def _clean_value(v):
    """Make a DB value JSON-friendly (dates -> ISO strings, Decimal -> float)."""
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return float(v)
    return v


def _clean_row(row: dict) -> dict:
    return {k: _clean_value(v) for k, v in row.items()}


# --------------------------------------------------------------------------------------
# 1. run_sql_query
# --------------------------------------------------------------------------------------

# Strips -- line comments and /* block */ comments before validation.
_COMMENT_RE = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)


def _validate_select(query: str) -> str:
    """Return the cleaned SQL if it's a single SELECT, else raise ValueError.

    Note: the semicolon check treats ';' as a statement separator even inside a
    string literal, so a query like `WHERE note = 'a;b'` is rejected. Acceptable
    for a defence-in-depth check; refine if a real query ever needs it.
    """
    if not query or not query.strip():
        raise ValueError("Empty query.")

    cleaned = _COMMENT_RE.sub(" ", query).strip()
    if not cleaned:
        raise ValueError("Query is only comments/whitespace.")

    # One optional trailing semicolon is fine; anything else means stacked statements.
    body = cleaned[:-1].strip() if cleaned.endswith(";") else cleaned
    if ";" in body:
        raise ValueError(
            "Multiple statements are not allowed (semicolon found mid-query). "
            "Submit a single SELECT."
        )

    if not body.lower().startswith("select"):
        raise ValueError(
            "Only a single read-only SELECT statement is allowed "
            "(query must start with SELECT)."
        )
    return body


def run_sql_query(query: str) -> dict:
    """Run one read-only SELECT.

    Returns {"rows": list[{column: value}], "truncated": bool}. `truncated` is True
    when the query would have returned more than MAX_ROWS rows, in which case `rows`
    holds exactly the first MAX_ROWS.

    Raises ValueError for anything that isn't a single SELECT, or for a SQL error.
    """
    safe_sql = _validate_select(query)

    try:
        with _connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(safe_sql)
            fetched = cur.fetchmany(MAX_ROWS + 1)  # +1 lets us detect truncation cheaply
    except psycopg2.Error as e:
        raise ValueError(f"SQL error: {str(e).strip()}") from e

    truncated = len(fetched) > MAX_ROWS
    rows = [_clean_row(r) for r in fetched[:MAX_ROWS]]
    return {"rows": rows, "truncated": truncated}


# --------------------------------------------------------------------------------------
# 2. get_summary_stats
# --------------------------------------------------------------------------------------

# aeser (raw) vs is_serious_derived: they "disagree" when the raw Y/N flag doesn't
# match the derived boolean. IS DISTINCT FROM is null-safe.
_DISAGREE = "(upper(aeser) = 'Y') IS DISTINCT FROM is_serious_derived"


def get_summary_stats() -> dict:
    """Fixed headline aggregates, one connection for the whole set."""
    with _connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:

        def scalar(sql: str):
            cur.execute(sql)
            return cur.fetchone()["v"]

        def table(sql: str) -> list[dict]:
            cur.execute(sql)
            return [_clean_row(r) for r in cur.fetchall()]

        return {
            "total_subjects": scalar("SELECT count(*) AS v FROM subjects"),
            "subjects_by_arm": table(
                "SELECT arm, count(*) AS n FROM subjects GROUP BY arm ORDER BY arm"
            ),
            "ae_count_by_severity": table(
                "SELECT aesev, count(*) AS n FROM adverse_events "
                "GROUP BY aesev ORDER BY aesev"
            ),
            "ae_serious_derived_true": scalar(
                "SELECT count(*) AS v FROM adverse_events WHERE is_serious_derived"
            ),
            "aeser_vs_derived_disagreements": scalar(
                f"SELECT count(*) AS v FROM adverse_events WHERE {_DISAGREE}"
            ),
            "vital_signs_rows": scalar("SELECT count(*) AS v FROM vital_signs"),
            "labs_rows": scalar("SELECT count(*) AS v FROM labs"),
        }


# --------------------------------------------------------------------------------------
# 3. run_quality_checks
# --------------------------------------------------------------------------------------

# Coarse, deliberately-wide plausibility bounds for the vital-sign test codes actually
# present in this dataset (DIABP, HEIGHT, PULSE, SYSBP, TEMP, WEIGHT). Units are inferred
# from the observed data: TEMP is Celsius (observed 34-38), HEIGHT cm (135-195), WEIGHT
# kg (33-108). Anything outside these bounds is almost certainly a data-entry error, not
# a real measurement. Bounds are wide on purpose - tighten only with clinical input.
# Labs are NOT range-checked: LBTESTCD spans dozens of assays with very different scales,
# so we only flag negative lab values (see below), nothing else.
_VS_RANGE_VIOLATION = """
    (vstestcd = 'SYSBP'  AND (result_value <= 0   OR result_value > 300))
 OR (vstestcd = 'DIABP'  AND (result_value <= 0   OR result_value > 200))
 OR (vstestcd = 'PULSE'  AND (result_value <= 0   OR result_value > 250))
 OR (vstestcd = 'TEMP'   AND (result_value < 30   OR result_value > 45))
 OR (vstestcd = 'HEIGHT' AND (result_value <= 0   OR result_value > 260))
 OR (vstestcd = 'WEIGHT' AND (result_value <= 0   OR result_value > 400))
"""

_QUALITY_CHECKS = [
    (
        "orphaned_records",
        "AE / VS / LB rows whose usubjid has no matching row in subjects.",
        """
        SELECT 'adverse_events' AS source_table, a.ae_id AS row_id, a.usubjid
        FROM adverse_events a
        WHERE NOT EXISTS (SELECT 1 FROM subjects s WHERE s.usubjid = a.usubjid)
        UNION ALL
        SELECT 'vital_signs', v.vs_id, v.usubjid
        FROM vital_signs v
        WHERE NOT EXISTS (SELECT 1 FROM subjects s WHERE s.usubjid = v.usubjid)
        UNION ALL
        SELECT 'labs', l.lb_id, l.usubjid
        FROM labs l
        WHERE NOT EXISTS (SELECT 1 FROM subjects s WHERE s.usubjid = l.usubjid)
        """,
    ),
    (
        "implausible_dates",
        "Adverse events whose end_date falls before their start_date.",
        """
        SELECT ae_id, usubjid, aeterm, start_date, end_date
        FROM adverse_events
        WHERE end_date < start_date
        """,
    ),
    (
        "missing_required_fields",
        "Rows missing a field that should always be populated "
        "(aeterm, vstestcd, or lbtestcd).",
        """
        SELECT 'adverse_events' AS source_table, ae_id AS row_id, usubjid,
               'aeterm' AS missing_field
        FROM adverse_events WHERE aeterm IS NULL
        UNION ALL
        SELECT 'vital_signs', vs_id, usubjid, 'vstestcd'
        FROM vital_signs WHERE vstestcd IS NULL
        UNION ALL
        SELECT 'labs', lb_id, usubjid, 'lbtestcd'
        FROM labs WHERE lbtestcd IS NULL
        """,
    ),
    (
        "implausible_values",
        "Negative lab values, or vital-sign values outside a wide plausibility "
        "band for their test code (see _VS_RANGE_VIOLATION comment for bounds).",
        f"""
        SELECT 'labs' AS source_table, lb_id AS row_id, usubjid, lbtestcd AS test_code,
               result_value, result_unit, 'negative result_value' AS reason
        FROM labs WHERE result_value < 0
        UNION ALL
        SELECT 'vital_signs', vs_id, usubjid, vstestcd,
               result_value, result_unit,
               'outside plausible range for ' || vstestcd
        FROM vital_signs WHERE {_VS_RANGE_VIOLATION}
        """,
    ),
    (
        "aeser_vs_derived_mismatch",
        "Events where the raw AESER flag disagrees with is_serious_derived "
        "(derived from AESDTH/AESLIFE/AESHOSP/AESDISAB/AESCONG/AESMIE). "
        "Project 1 found AESER systematically under-reports seriousness.",
        f"""
        SELECT ae_id, usubjid, aeterm, aedecod, aesev, aeser,
               is_serious_derived, aeout
        FROM adverse_events
        WHERE {_DISAGREE}
        ORDER BY ae_id
        """,
    ),
]


def run_quality_checks() -> list[dict]:
    """Run the fixed battery of checks.

    Each result: {check_name, description, count, example_rows} where example_rows
    is at most 5 offending rows.
    """
    results = []
    with _connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        for name, description, detail_sql in _QUALITY_CHECKS:
            cur.execute(f"SELECT count(*) AS v FROM ({detail_sql}) _t")
            count = cur.fetchone()["v"]

            cur.execute(f"SELECT * FROM ({detail_sql}) _t LIMIT 5")
            examples = [_clean_row(r) for r in cur.fetchall()]

            results.append(
                {
                    "check_name": name,
                    "description": description,
                    "count": count,
                    "example_rows": examples,
                }
            )
    return results
