"""Standalone exercise of the three SQL tools in app/tools.py.

No agent loop, no API calls - just imports the functions and prints what they
return, so the output can be eyeballed for correctness.

Run from the backend/ directory with the venv active:
    python -m scripts.test_tools
"""

from __future__ import annotations

import json

from app.tools import get_summary_stats, run_quality_checks, run_sql_query


def show(title: str, obj) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")
    print(json.dumps(obj, indent=2, default=str))


def main() -> None:
    # ---- 1. run_sql_query -------------------------------------------------------
    show(
        "run_sql_query - subjects per treatment arm",
        run_sql_query(
            "SELECT arm, count(*) AS n FROM subjects GROUP BY arm ORDER BY arm"
        ),
    )

    show(
        "run_sql_query - comment stripped, trailing semicolon allowed",
        run_sql_query("  -- how many severe AEs?\n SELECT count(*) FROM adverse_events WHERE aesev = 'SEVERE';"),
    )

    capped = run_sql_query("SELECT vs_id, usubjid, vstestcd, result_value FROM vital_signs")
    print(f"\n{'=' * 72}\nrun_sql_query - 500-row cap on a big result\n{'=' * 72}")
    print(f"truncated: {capped['truncated']}")
    print(f"len(rows): {len(capped['rows'])}")
    print(f"first row: {json.dumps(capped['rows'][0], default=str)}")

    print(f"\n{'=' * 72}\nrun_sql_query - rejections (each should raise ValueError)\n{'=' * 72}")
    for bad in [
        "DELETE FROM subjects",
        "UPDATE subjects SET age = 0",
        "SELECT 1; DROP TABLE subjects",
        "SELECT * FROM subjects; SELECT * FROM labs;",
        "INSERT INTO subjects (usubjid) VALUES ('x')",
        "   ",
    ]:
        try:
            run_sql_query(bad)
            print(f"  NOT REJECTED (bug!): {bad!r}")
        except ValueError as e:
            print(f"  rejected: {bad!r}\n      -> {e}")

    # ---- 2. get_summary_stats -------------------------------------------------
    show("get_summary_stats()", get_summary_stats())

    # ---- 3. run_quality_checks ----------------------------------------------
    checks = run_quality_checks()
    show("run_quality_checks()", checks)
    print("\nquality-check summary:")
    for c in checks:
        print(f"  {c['check_name']:<28} count={c['count']}")


if __name__ == "__main__":
    main()
