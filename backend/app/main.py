"""FastAPI app entrypoint.

Right now this only exposes read-only sanity endpoints so you can confirm the
loaded data is queryable. The Claude tool-use agent loop comes in a later step.
"""

from fastapi import FastAPI
from sqlalchemy import func, select

from app.db import ALL_TABLES, get_engine

app = FastAPI(title="Clinical Data-Quality Reviewer", version="0.1.0")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/db/summary")
def db_summary():
    """Row count per table — quick check that the loader ran."""
    engine = get_engine()
    counts = {}
    with engine.connect() as conn:
        for table in ALL_TABLES:
            counts[table.name] = conn.execute(
                select(func.count()).select_from(table)
            ).scalar_one()
    return counts
