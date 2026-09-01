"""The Claude tool-use agent loop.

Stateless: the caller (the frontend) owns the full conversation history and sends
it on every request. run_chat_turn takes that history, runs the
call -> maybe-execute-tools -> call loop until Claude stops asking for tools, and
returns ONLY the messages generated this turn so the caller can append them.

Model matches Project 1's narrative generator (claude-sonnet-5) for consistency.
"""

from __future__ import annotations

import json
import os

import anthropic
import psycopg2
from dotenv import load_dotenv

from app.tools import get_summary_stats, run_quality_checks, run_sql_query

load_dotenv()

MODEL = "claude-sonnet-5"
MAX_TOKENS = 8192
MAX_TOOL_ITERATIONS = 12  # hard stop so a misbehaving loop can't run forever


SYSTEM_PROMPT = """You are a data-quality assistant for a clinical trial dataset (CDISCPILOT01 — a real
CDISC pilot study with 306 subjects across DM, AE, VS, and LB domains). You have three
tools: run_sql_query for arbitrary read-only questions, get_summary_stats for quick
high-level counts, and run_quality_checks for a fixed battery of data-quality checks.

Critical rule: you must never answer a factual question about this dataset from memory
or by estimating — every number in your response must come from a tool call you actually
made in this conversation. If a question can't be answered by the schema available
(subjects, adverse_events, vital_signs, labs), say so rather than guessing.

When reporting run_quality_checks findings, explain them in plain language a clinical
study team member would understand, and note clinical significance where relevant (e.g.,
a fatal event with a disputed seriousness flag is a materially different finding than a
minor field omission) — don't just recite counts.

If a query returns zero rows, report that plainly rather than treating it as an error."""


# Included in run_sql_query's tool description — there is no separate schema-discovery tool.
_SCHEMA_DOC = """
Database schema (PostgreSQL). All child tables link to subjects on usubjid.

subjects — one row per subject
  usubjid (text, PK), siteid (text), age (int), age_unit (text), sex (text),
  race (text), ethnic (text), arm (text), country (text)

adverse_events — one row per adverse event
  ae_id (int, PK), usubjid (text), aeseq (int), aeterm (text, verbatim term),
  aedecod (text, MedDRA preferred term), aebodsys (text, body system),
  aesev (text: MILD | MODERATE | SEVERE), aesev_rank (int: 1 | 2 | 3),
  aeser (text: Y | N — raw sponsor flag, known to under-report seriousness),
  is_serious_derived (boolean — derived from the SDTM seriousness sub-flags,
  more reliable than aeser), aerel (text, causality), aeout (text, outcome),
  start_date (date), end_date (date, null if ongoing/unknown)

vital_signs — one row per vital-sign measurement
  vs_id (int, PK), usubjid (text), vstestcd (text: SYSBP | DIABP | PULSE | TEMP
  | HEIGHT | WEIGHT), vstest (text, long name), result_value (numeric),
  result_unit (text), visit (text), visit_date (date)

labs — one row per lab result
  lb_id (int, PK), usubjid (text), lbtestcd (text), lbtest (text, long name),
  lbcat (text, panel), result_value (numeric), result_unit (text),
  normal_range_indicator (text: e.g. NORMAL | HIGH | LOW — reliable), visit (text),
  visit_date (date)
""".strip()


TOOLS = [
    {
        "name": "run_sql_query",
        "description": (
            "Run a single read-only SQL SELECT against the clinical trial database and "
            "get the rows back as JSON. Use this for any specific factual question that "
            "get_summary_stats and run_quality_checks don't already answer. Only a "
            "single SELECT is accepted (no INSERT/UPDATE/DELETE, no multiple "
            "statements) — anything else is rejected before it reaches the database. "
            "Results are capped at 500 rows; if that happens the response includes "
            '"truncated": true, so add a LIMIT or an aggregate.\n\n' + _SCHEMA_DOC
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "One PostgreSQL SELECT statement.",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_summary_stats",
        "description": (
            "Return a fixed set of high-level counts, no arguments: total subject "
            "count, subject count per treatment arm, adverse-event count per severity, "
            "count of events flagged serious by the derived rule, count of events where "
            "the raw aeser flag disagrees with is_serious_derived, and the vital_signs "
            "and labs row counts. Use for 'give me an overview' style questions."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_quality_checks",
        "description": (
            "Run the fixed data-quality battery, no arguments. Returns one entry per "
            "check with check_name, description, count, and up to 5 example rows: "
            "(a) orphaned AE/VS/LB rows with no matching subject, (b) adverse events "
            "whose end_date precedes start_date, (c) rows missing a required field "
            "(aeterm / vstestcd / lbtestcd), (d) implausible vital-sign or lab values, "
            "(e) events where aeser disagrees with is_serious_derived. Use when the "
            "user asks for a data-quality scan / review / check."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


_DISPATCH = {
    "run_sql_query": lambda tool_input: run_sql_query(tool_input["query"]),
    "get_summary_stats": lambda _tool_input: get_summary_stats(),
    "run_quality_checks": lambda _tool_input: run_quality_checks(),
}


def _execute_tool(name: str, tool_input: dict) -> tuple[str, bool]:
    """Run one tool. Returns (json_string, is_error)."""
    fn = _DISPATCH.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {name}"}), True
    try:
        return json.dumps(fn(tool_input), default=str), False
    except psycopg2.OperationalError:
        # Connection-level failure - almost always a paused free-tier Supabase
        # instance. Hand Claude something it can relay, not a stack trace.
        return (
            json.dumps(
                {
                    "error": "Database unreachable — it may be paused after inactivity; "
                    "visiting the Supabase dashboard resumes it."
                }
            ),
            True,
        )
    except (ValueError, KeyError) as e:
        # ValueError: bad SQL / rejected query. KeyError: missing 'query' arg.
        return json.dumps({"error": str(e)}), True


def run_chat_turn(messages: list[dict]) -> list[dict]:
    """Advance the conversation by one user turn.

    `messages` is the full history in Anthropic format, ending with the newest user
    message. Returns just the messages generated this turn (assistant tool_use
    messages, tool_result messages, and the final assistant text message).
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    conversation = list(messages)
    new_messages: list[dict] = []

    for _ in range(MAX_TOOL_ITERATIONS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=conversation,
        )

        assistant_message = {
            "role": "assistant",
            "content": [block.model_dump() for block in response.content],
        }
        conversation.append(assistant_message)
        new_messages.append(assistant_message)

        if response.stop_reason != "tool_use":
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            output, is_error = _execute_tool(block.name, block.input)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                    "is_error": is_error,
                }
            )

        tool_result_message = {"role": "user", "content": tool_results}
        conversation.append(tool_result_message)
        new_messages.append(tool_result_message)
    else:
        # Ran out of iterations without a natural end_turn.
        new_messages.append(
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "I stopped after reaching the tool-call limit for one turn. "
                            "Please narrow the question and try again."
                        ),
                    }
                ],
            }
        )

    return new_messages
