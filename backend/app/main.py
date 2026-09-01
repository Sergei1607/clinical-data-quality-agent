"""FastAPI app entrypoint.

Exposes:
  GET  /health       - liveness check
  GET  /db/summary   - row count per table (confirms the loader ran)
  POST /chat         - one turn of the Claude tool-use agent (stateless)
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from app.agent import run_chat_turn
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


class ChatRequest(BaseModel):
    # Full conversation so far, in Anthropic message format, ending with the newest
    # user turn. The server keeps no session state — the client owns the history.
    messages: list[dict]


class ChatResponse(BaseModel):
    # Only the messages generated this turn: assistant tool_use messages, tool_result
    # messages, and the final assistant text message. The client appends these.
    new_messages: list[dict]


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    if not request.messages:
        raise HTTPException(status_code=400, detail="messages must not be empty")
    try:
        new_messages = run_chat_turn(request.messages)
    except Exception as e:  # noqa: BLE001 - surface any agent/API failure as a 502
        raise HTTPException(status_code=502, detail=f"agent error: {e}") from e
    return ChatResponse(new_messages=new_messages)
