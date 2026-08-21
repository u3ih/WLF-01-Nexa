"""Routing prompts: pick one read-only tool, or none at all.

Two shapes, because the two model modes need different things. A model with
native function calling gets TOOL_CHOICE plus the JSON schemas; a plain
chat model gets ROUTER, which asks for the same decision as JSON text.
"""

from __future__ import annotations

from typing import Any

from ..tools import SPECS, data_coverage

TOOL_CHOICE = """Decide first whether this message asks anything about the
statement. If it does, call exactly one tool. If it does not — a greeting, a
thank-you, a goodbye, asking who or what you are, or any other chit-chat —
answer conversationally and call no tool at all. Judge the meaning, not the
wording: a greeting attached to a real question is a real question."""

# The model is the only part of the chain that reads a bare month name as a
# period, so it is the part that has to be told which year that month is in.
# Without this it either drops the period — reporting the latest month as though
# it were the one asked for — or resolves it against the wall-clock year, which
# is not the year this sample export covers.
TEMPORAL = """Time context. The statement data covers {first} to {last}.
Month keys held: {months}.
The user may name a period in any wording, in their own language, and usually
without a year: a month name or a month number on its own, a quarter, "this
month", "last month". Resolve whatever they name into the `key` argument and
pass it:
- a month, however written -> "{year}-MM"; month 7 -> "{year}-07"
- a quarter -> "{year}-Qn"; the second quarter -> "{year}-Q2"
- the current or most recent month, or no period named at all -> "{latest}"
- the whole year -> "{year}"
A period named without a year means {year}, not the current wall-clock year.
If the user names a period outside the range above, pass that key anyway: the
tool reports that the data does not cover it. Never answer about a period other
than the one that was asked for."""

ROUTER = """You choose ONE tool to answer the user's question about their
statement. Reply with JSON only, no prose, no code fence:

{{"tool": "<tool name>", "args": {{<arguments or empty>}}}}

Available tools:
{tool_list}

Guidance:
- "how much did I spend", "report", "this month", "fees" -> get_report
- "what is this charge", "what does X mean", a bare amount -> explain_charge
- "receipt", "email", "confirmation" -> get_email_recon
- "not on the card", "wallet", "duplicate deposit" -> get_tri_source
- "subscriptions", "recurring", "price went up" -> list_subscriptions
- "anything unusual", "duplicates", "double charge" -> get_findings
- "send the report to my email" -> draft_report_email
- "check again", "any new issues" -> run_monitor_scan
- "how do I cancel" -> get_cancellation_guide
- a message that asks nothing about the statement — a greeting, thanks, a
  goodbye, "who are you", "what can you do", or any other chit-chat
  -> chat_only
- a real question about the statement that you cannot place -> get_overview

Judge by what the message means, not by the words it happens to use. A greeting
followed by a real question is a real question: route it to the tool that
answers the question.

{temporal}

User question: {question}
JSON:"""

# Arguments the tools declare as numbers; everything else is a string.
NUMBER_ARGS = {"amount", "min_amount", "limit"}


def tool_list_text() -> str:
    lines = []
    for spec in SPECS:
        args = ", ".join(spec["parameters"]) or "none"
        lines.append(f"- {spec['name']}({args}): {spec['description']}")
    return "\n".join(lines)


def temporal_note() -> str:
    """The period vocabulary, filled in from the export that is loaded.

    Empty when the dataset cannot be read: a prompt that names no range is
    worse than none, and the deterministic path still answers.
    """
    try:
        cover = data_coverage()
    except Exception:                                   # noqa: BLE001
        return ""
    return TEMPORAL.format(
        first=cover["first_day"], last=cover["last_day"],
        months=", ".join(cover["months"]),
        year=cover["latest_month"][:4], latest=cover["latest_month"],
    )


def router_prompt(question: str) -> str:
    return ROUTER.format(tool_list=tool_list_text(), question=question,
                         temporal=temporal_note())


def native_tool_schemas() -> list[dict[str, Any]]:
    """Ollama / OpenAI-style function schemas for models that support tools."""
    out = []
    for spec in SPECS:
        properties = {}
        for name, description in spec["parameters"].items():
            properties[name] = {
                "type": "number" if name in NUMBER_ARGS else "string",
                "description": description,
            }
        out.append({
            "type": "function",
            "function": {
                "name": spec["name"],
                "description": spec["description"],
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": [],
                },
            },
        })
    return out
