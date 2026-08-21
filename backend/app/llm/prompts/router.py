"""Routing prompts: pick one read-only tool, or none at all.

Two shapes, because the two model modes need different things. A model with
native function calling gets TOOL_CHOICE plus the JSON schemas; a plain
chat model gets ROUTER, which asks for the same decision as JSON text.
"""

from __future__ import annotations

from typing import Any

from ..tools import SPECS

TOOL_CHOICE = """Decide first whether this message asks anything about the
statement. If it does, call exactly one tool. If it does not — a greeting, a
thank-you, a goodbye, asking who or what you are, or any other chit-chat —
answer conversationally and call no tool at all. Judge the meaning, not the
wording: a greeting attached to a real question is a real question."""

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


def router_prompt(question: str) -> str:
    return ROUTER.format(tool_list=tool_list_text(), question=question)


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
