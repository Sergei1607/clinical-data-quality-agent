"""Send a few real conversations through the agent loop and print the full trace.

Calls run_chat_turn directly (no HTTP, no frontend). For each test question it
prints every message generated that turn - assistant text, each tool_use with its
arguments (so you can see the actual SQL), and each tool_result - so the reasoning
trace is visible, not just the final answer.

Run from backend/ with the venv active and a real ANTHROPIC_API_KEY in .env:
    python -m scripts.test_chat
"""

from __future__ import annotations

import json
import textwrap

from app.agent import run_chat_turn

TESTS = [
    # Should lean on get_summary_stats.
    "Give me a high-level overview of this dataset - how many subjects, how are they "
    "split across treatment arms, and how do the adverse events break down by severity?",
    # Should require run_sql_query with a JOIN + WHERE.
    "Which subjects had a SEVERE adverse event with a fatal outcome? Give me their "
    "usubjid, age, sex, and treatment arm, plus the adverse-event term.",
    # Should trigger run_quality_checks.
    "Run the data-quality scan on this dataset and tell me what you find, in plain "
    "language, with any clinical significance called out.",
]


def _shorten(value: str, width: int = 1400) -> str:
    return value if len(value) <= width else value[:width] + f"  ... [{len(value) - width} more chars]"


def print_message(msg: dict) -> None:
    role = msg["role"]
    for block in msg["content"]:
        btype = block.get("type")
        if btype == "text":
            print(f"\n  [{role} · text]")
            print(textwrap.indent(block["text"].strip(), "    "))
        elif btype == "thinking":
            print(f"\n  [{role} · thinking]  ({len(block.get('thinking', ''))} chars, not shown)")
        elif btype == "tool_use":
            print(f"\n  [{role} · tool_use]  -> {block['name']}")
            print(textwrap.indent(json.dumps(block["input"], indent=2), "    "))
        elif btype == "tool_result":
            tag = "tool_result (ERROR)" if block.get("is_error") else "tool_result"
            content = block["content"]
            if isinstance(content, list):
                content = json.dumps(content)
            print(f"\n  [{role} · {tag}]  (tool_use_id {block['tool_use_id']})")
            print(textwrap.indent(_shorten(content), "    "))
        else:
            print(f"\n  [{role} · {btype}]  {json.dumps(block)[:200]}")


def main() -> None:
    for i, question in enumerate(TESTS, 1):
        print("\n" + "=" * 78)
        print(f"TEST {i}")
        print("=" * 78)
        print("\n  [user · text]")
        print(textwrap.indent(textwrap.fill(question, 74), "    "))

        history = [{"role": "user", "content": question}]
        new_messages = run_chat_turn(history)

        tool_calls = [
            b["name"]
            for m in new_messages
            for b in m["content"]
            if b.get("type") == "tool_use"
        ]
        for msg in new_messages:
            print_message(msg)

        print(f"\n  --- tools called this turn: {tool_calls or 'NONE'} ---")


if __name__ == "__main__":
    main()
