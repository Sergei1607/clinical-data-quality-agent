"""Database engine + schema definitions.

Shared by the FastAPI app and the one-time loader script (backend/scripts/load_data.py)
so the table shapes only live in one place. Schema mirrors the one documented in
../claude.md.
"""

import os

from dotenv import load_dotenv
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
)

load_dotenv()


def get_engine(env_var: str = "DATABASE_URL"):
    """Create a SQLAlchemy engine from the connection string in `env_var`.

    Defaults to DATABASE_URL (the owner role, used by the loader). Pass
    env_var="AGENT_DATABASE_URL" for the SELECT-only role — same pattern
    tools.py uses. Raises a clear error if the chosen var is unset.
    """
    url = os.getenv(env_var)
    if not url:
        raise RuntimeError(
            f"{env_var} is not set. Copy backend/.env.example to backend/.env "
            "and fill in your Supabase connection string(s)."
        )
    # pool_pre_ping avoids stale-connection errors after Supabase's idle pause.
    return create_engine(url, pool_pre_ping=True, future=True)


metadata = MetaData()

# One row per subject (from SDTM DM).
subjects = Table(
    "subjects",
    metadata,
    Column("usubjid", String, primary_key=True),
    Column("siteid", String),
    Column("age", Integer),
    Column("age_unit", String),
    Column("sex", String),
    Column("race", String),
    Column("ethnic", String),
    Column("arm", String),
    Column("country", String),
)

# One row per adverse event (from SDTM AE).
adverse_events = Table(
    "adverse_events",
    metadata,
    Column("ae_id", Integer, primary_key=True),
    Column("usubjid", String, index=True),
    Column("aeseq", Integer),
    Column("aeterm", String),
    Column("aedecod", String),
    Column("aebodsys", String),
    Column("aesev", String),
    Column("aesev_rank", Integer),  # MILD/MODERATE/SEVERE -> 1/2/3
    Column("aeser", String),  # raw AESER flag (unreliable per Project 1 finding)
    Column("is_serious_derived", Boolean),  # computed from the AES* sub-flags
    Column("aerel", String),
    Column("aeout", String),
    Column("start_date", Date),  # cast from AESTDTC
    Column("end_date", Date),  # cast from AEENDTC
)

# One row per vital-sign measurement (from SDTM VS).
vital_signs = Table(
    "vital_signs",
    metadata,
    Column("vs_id", Integer, primary_key=True),
    Column("usubjid", String, index=True),
    Column("vstestcd", String),
    Column("vstest", String),
    Column("result_value", Float),  # from VSSTRESN
    Column("result_unit", String),  # from VSSTRESU
    Column("visit", String),
    Column("visit_date", Date),  # cast from VSDTC
)

# One row per lab result (from SDTM LB).
labs = Table(
    "labs",
    metadata,
    Column("lb_id", Integer, primary_key=True),
    Column("usubjid", String, index=True),
    Column("lbtestcd", String),
    Column("lbtest", String),
    Column("lbcat", String),
    Column("result_value", Float),  # from LBSTRESN
    Column("result_unit", String),  # from LBSTRESU
    Column("normal_range_indicator", String),  # from LBNRIND (reliable, unlike AESER)
    Column("visit", String),
    Column("visit_date", Date),  # cast from LBDTC
)

ALL_TABLES = [subjects, adverse_events, vital_signs, labs]
