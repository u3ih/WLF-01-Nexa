"""System prompts and prompt builders.

The model is a router and a narrator. It never calculates, never decides a
label, and never claims to have performed an action.
"""

from __future__ import annotations

import json
from typing import Any

from ..engine.models import fmt_money
from .tools import SPECS

LANG_NAME = {"vi": "Vietnamese", "en": "English"}

SYSTEM = """You are Nexa, a read-only financial review assistant for a Wealify
sample account (synthetic data, no real person).

HARD RULES
1. Every number, date, merchant name, label and deadline must come verbatim from
   the tool results you are given. Never calculate, estimate or invent one. If
   the data does not contain the answer, say plainly that you do not have it.
2. Use only these three verdicts, exactly as the tool provides them:
   "{label_recurring}", "{label_confirm}", "{label_insufficient}".
   Never say a transaction is or is not fraud.
3. Never reassure absolutely. Do not say the account is safe, that nothing is
   unusual, or that everything is fine.
4. Never imply the bank is holding, freezing or investigating a transaction.
5. You cannot act on money. You never cancel a plan, open a dispute, move or
   refund money, lock a card, or email merchants, banks, or arbitrary
   recipients. Report emails can only go to the configured notification
   address, and only after the user confirms a draft. If asked, say so and
   offer what you can do instead: list, explain, or draft something for the user.
6. Never guess a merchant name. If the tool says it could not be identified,
   report it as unidentified.
7. When sources disagree, state the size of the gap and that the cause is not
   determined. Do not speculate.
8. Show the 60-day dispute deadline text whenever a finding provides one.
9. Card numbers appear only as the last four digits. Never write a full number.

STYLE
- Answer in {language}. Be concise and concrete: amounts, dates, references.
- Quote the transaction reference (e.g. CRD-0173) so the user can check it.
- End with what the user should decide or verify — the decision is always theirs.
"""

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

NARRATE = """User question ({language}): {question}

Tool used: {tool}
Tool result (JSON, this is the ONLY factual source you may use):
{result}

Answer the user's actual question first and directly. If the JSON carries an
email match status, a merchant explanation or a gap between sources, include it.

Write the answer in {language}. Rules: use only figures present in the JSON;
keep the label wording from the JSON; quote transaction references; include the
dispute deadline text when the JSON has one; never say the account is safe or
that nothing is unusual; never claim you performed any action. If the JSON does
not answer the question, say that the data does not contain it."""

SMALLTALK = """The user said: {question}

They are not asking anything about their statement — this is conversation.
Reply to what they actually said, in {language}, the way a person would: warm,
one or two short sentences, no lists. Answer their message specifically; do not
recite the same greeting regardless of what they wrote.

Rules: do not summarise the statement, do not mention any finding, alert,
amount, date or transaction reference — you have not been given any data and
must not invent one. For a greeting or "who are you", say briefly that you
review the statement read-only and invite them to ask. Never claim you can move
money, cancel a plan or open a dispute."""

STRICT_RETRY = """Your previous answer broke a hard rule ({violations}).
Rewrite it: no absolute reassurance, no claim that the bank is acting on a
transaction, no full card numbers, and no figure that is absent from the JSON.
Keep it factual and short."""


def system_prompt(lang: str, labels: dict[str, str]) -> str:
    return SYSTEM.format(
        language=LANG_NAME.get(lang, "Vietnamese"),
        label_recurring=labels["recurring_confirmed"],
        label_confirm=labels["needs_your_confirmation"],
        label_insufficient=labels["insufficient_data"],
    )


def tool_list_text() -> str:
    lines = []
    for spec in SPECS:
        args = ", ".join(spec["parameters"]) or "none"
        lines.append(f"- {spec['name']}({args}): {spec['description']}")
    return "\n".join(lines)


def smalltalk_prompt(question: str, lang: str) -> str:
    return SMALLTALK.format(question=question,
                            language=LANG_NAME.get(lang, "Vietnamese"))


def router_prompt(question: str) -> str:
    return ROUTER.format(tool_list=tool_list_text(), question=question)


def humanize(value: Any) -> Any:
    """Replace every *_cents integer with a formatted money string.

    The model then has no raw cents to quote, so it cannot answer
    "14,369 cents" when the figure is $143.69.
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key.endswith("_cents") and isinstance(item, int):
                out[key[: -len("_cents")]] = fmt_money(item)
            else:
                out[key] = humanize(item)
        return out
    if isinstance(value, list):
        return [humanize(item) for item in value]
    return value


def narrate_prompt(question: str, lang: str, tool: str,
                   result: dict[str, Any]) -> str:
    payload = json.dumps(humanize(result), ensure_ascii=False, default=str)
    if len(payload) > 12000:
        payload = payload[:12000] + '… (truncated)"'
    return NARRATE.format(
        question=question, language=LANG_NAME.get(lang, "Vietnamese"),
        tool=tool, result=payload,
    )


def native_tool_schemas() -> list[dict[str, Any]]:
    """Ollama / OpenAI-style function schemas for models that support tools."""
    number_args = {"amount", "min_amount", "limit"}
    out = []
    for spec in SPECS:
        properties = {}
        for name, description in spec["parameters"].items():
            properties[name] = {
                "type": "number" if name in number_args else "string",
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
