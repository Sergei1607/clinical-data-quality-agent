"""One-time (re-runnable) data loader for the Clinical Data-Quality Reviewer.

What it does:
  1. Gets the four SDTM domains (DM, AE, VS, LB) as .xpt SAS Transport files —
     from backend/data/ if present, otherwise downloads them from the CDISC
     pilot submission package on GitHub.
  2. Parses each with pyreadstat.
  3. Transforms each domain into the schema in app/db.py, adding the derived
     columns (aesev_rank, is_serious_derived, real DATE columns).
  4. Drops + recreates the four tables in Postgres (safe to re-run — no dup rows).
  5. Loads the transformed data and prints a row count per table.

Usage (from the backend/ directory, venv active, .env filled in):
    python -m scripts.load_data
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

import pandas as pd
import pyreadstat

from app.db import (
    ALL_TABLES,
    adverse_events,
    get_engine,
    labs,
    metadata,
    subjects,
    vital_signs,
)

# --------------------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# raw.githubusercontent base for cdisc-org/sdtm-adam-pilot-project (default branch: master)
GITHUB_RAW_BASE = (
    "https://raw.githubusercontent.com/cdisc-org/sdtm-adam-pilot-project/master/"
    "updated-pilot-submission-package/900172/m5/datasets/cdiscpilot01/tabulations/sdtm/"
)

DOMAIN_FILES = {
    "DM": "dm.xpt",
    "AE": "ae.xpt",
    "VS": "vs.xpt",
    "LB": "lb.xpt",
}

# The six AE "seriousness" sub-flags. is_serious_derived is True if any == 'Y'.
SERIOUS_FLAGS = ["AESDTH", "AESLIFE", "AESHOSP", "AESDISAB", "AESCONG", "AESMIE"]

SEVERITY_RANK = {"MILD": 1, "MODERATE": 2, "SEVERE": 3}


# --------------------------------------------------------------------------------------
# Step 1 — get the .xpt files
# --------------------------------------------------------------------------------------


def ensure_files() -> dict[str, Path]:
    """Return {domain: local path}, downloading any file not already in backend/data/."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for domain, filename in DOMAIN_FILES.items():
        dest = DATA_DIR / filename
        if dest.exists() and dest.stat().st_size > 0:
            print(f"  [{domain}] using local file  {dest}  ({dest.stat().st_size:,} bytes)")
        else:
            url = GITHUB_RAW_BASE + filename
            print(f"  [{domain}] downloading         {url}")
            urllib.request.urlretrieve(url, dest)
            print(f"           saved -> {dest}  ({dest.stat().st_size:,} bytes)")
        paths[domain] = dest
    return paths


# --------------------------------------------------------------------------------------
# Step 2 — parse
# --------------------------------------------------------------------------------------


def read_xpt(path: Path) -> pd.DataFrame:
    """Parse an .xpt file into a DataFrame with UPPERCASE column names."""
    df, _meta = pyreadstat.read_xport(str(path), encoding="latin1")
    df.columns = [c.upper() for c in df.columns]
    return df


# --------------------------------------------------------------------------------------
# Step 3 — transform helpers
# --------------------------------------------------------------------------------------


def to_date(series: pd.Series) -> pd.Series:
    """Cast an SDTM --DTC ISO 8601 string column to python date objects.

    Handles full and partial dates; anything unparseable becomes NaT/None.
    """
    dt = pd.to_datetime(series, format="ISO8601", errors="coerce")
    return dt.dt.date.where(dt.notna(), None)


def col(df: pd.DataFrame, name: str) -> pd.Series:
    """Return df[name] if it exists, else an all-None column (keeps transforms robust
    to minor domain-to-domain variation in the pilot data)."""
    if name in df.columns:
        return df[name]
    print(f"    note: column {name} not present — filling with NULL")
    return pd.Series([None] * len(df), index=df.index)


def strip_str(series: pd.Series) -> pd.Series:
    """Trim whitespace; turn empty strings into None."""
    s = series.astype("string").str.strip()
    return s.where(s.notna() & (s.str.len() > 0), None)


# --------------------------------------------------------------------------------------
# Step 3 — per-domain transforms
# --------------------------------------------------------------------------------------


def transform_dm(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(
        {
            "usubjid": strip_str(col(df, "USUBJID")),
            "siteid": strip_str(col(df, "SITEID")),
            "age": pd.to_numeric(col(df, "AGE"), errors="coerce").astype("Int64"),
            "age_unit": strip_str(col(df, "AGEU")),
            "sex": strip_str(col(df, "SEX")),
            "race": strip_str(col(df, "RACE")),
            "ethnic": strip_str(col(df, "ETHNIC")),
            "arm": strip_str(col(df, "ARM")),
            "country": strip_str(col(df, "COUNTRY")),
        }
    )
    return out.dropna(subset=["usubjid"]).drop_duplicates(subset=["usubjid"])


def transform_ae(df: pd.DataFrame) -> pd.DataFrame:
    sev = strip_str(col(df, "AESEV")).str.upper()

    present_flags = [f for f in SERIOUS_FLAGS if f in df.columns]
    if present_flags:
        flags = df[present_flags].apply(lambda s: s.astype("string").str.strip().str.upper())
        is_serious = (flags == "Y").any(axis=1)
    else:
        is_serious = pd.Series(False, index=df.index)

    out = pd.DataFrame(
        {
            "usubjid": strip_str(col(df, "USUBJID")),
            "aeseq": pd.to_numeric(col(df, "AESEQ"), errors="coerce").astype("Int64"),
            "aeterm": strip_str(col(df, "AETERM")),
            "aedecod": strip_str(col(df, "AEDECOD")),
            "aebodsys": strip_str(col(df, "AEBODSYS")),
            "aesev": sev,
            "aesev_rank": sev.map(SEVERITY_RANK).astype("Int64"),
            "aeser": strip_str(col(df, "AESER")),
            "is_serious_derived": is_serious.astype(bool),
            "aerel": strip_str(col(df, "AEREL")),
            "aeout": strip_str(col(df, "AEOUT")),
            "start_date": to_date(col(df, "AESTDTC")),
            "end_date": to_date(col(df, "AEENDTC")),
        }
    )
    out = out.dropna(subset=["usubjid"]).reset_index(drop=True)
    out.insert(0, "ae_id", range(1, len(out) + 1))
    return out


def transform_vs(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(
        {
            "usubjid": strip_str(col(df, "USUBJID")),
            "vstestcd": strip_str(col(df, "VSTESTCD")),
            "vstest": strip_str(col(df, "VSTEST")),
            "result_value": pd.to_numeric(col(df, "VSSTRESN"), errors="coerce"),
            "result_unit": strip_str(col(df, "VSSTRESU")),
            "visit": strip_str(col(df, "VISIT")),
            "visit_date": to_date(col(df, "VSDTC")),
        }
    )
    out = out.dropna(subset=["usubjid"]).reset_index(drop=True)
    out.insert(0, "vs_id", range(1, len(out) + 1))
    return out


def transform_lb(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(
        {
            "usubjid": strip_str(col(df, "USUBJID")),
            "lbtestcd": strip_str(col(df, "LBTESTCD")),
            "lbtest": strip_str(col(df, "LBTEST")),
            "lbcat": strip_str(col(df, "LBCAT")),
            "result_value": pd.to_numeric(col(df, "LBSTRESN"), errors="coerce"),
            "result_unit": strip_str(col(df, "LBSTRESU")),
            "normal_range_indicator": strip_str(col(df, "LBNRIND")),
            "visit": strip_str(col(df, "VISIT")),
            "visit_date": to_date(col(df, "LBDTC")),
        }
    )
    out = out.dropna(subset=["usubjid"]).reset_index(drop=True)
    out.insert(0, "lb_id", range(1, len(out) + 1))
    return out


# --------------------------------------------------------------------------------------
# Step 4 + 5 — schema + load
# --------------------------------------------------------------------------------------


def recreate_schema(engine) -> None:
    print("  dropping + recreating tables (subjects, adverse_events, vital_signs, labs)")
    metadata.drop_all(engine)
    metadata.create_all(engine)


def load_table(engine, table, frame: pd.DataFrame) -> int:
    frame.to_sql(
        table.name,
        engine,
        if_exists="append",
        index=False,
        method="multi",
        chunksize=1000,
    )
    return len(frame)


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------


def main() -> int:
    print("\n== Step 1: locate / download .xpt files ==")
    paths = ensure_files()

    print("\n== Step 2: parse .xpt files ==")
    raw = {domain: read_xpt(path) for domain, path in paths.items()}
    for domain, df in raw.items():
        print(f"  [{domain}] parsed {len(df):,} rows, {len(df.columns)} columns")

    print("\n== Step 3: transform to target schema ==")
    frames = {
        subjects: transform_dm(raw["DM"]),
        adverse_events: transform_ae(raw["AE"]),
        vital_signs: transform_vs(raw["VS"]),
        labs: transform_lb(raw["LB"]),
    }
    for table, frame in frames.items():
        print(f"  [{table.name}] {len(frame):,} rows ready")

    print("\n== Step 4: (re)create schema in Postgres ==")
    engine = get_engine()
    recreate_schema(engine)

    print("\n== Step 5: load ==")
    for table in ALL_TABLES:
        n = load_table(engine, table, frames[table])
        print(f"  [{table.name}] loaded {n:,} rows")

    print("\n== Done. Row counts (verify against known dataset size) ==")
    from sqlalchemy import func, select

    with engine.connect() as conn:
        for table in ALL_TABLES:
            count = conn.execute(select(func.count()).select_from(table)).scalar_one()
            print(f"  {table.name:<16} {count:,}")
    print("\n  (Project 1 found 1,191 AE events for study CDISCPILOT01.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
