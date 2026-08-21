"""Narration prompts: turn one tool result into prose, and the retry that
follows a rule breach.
"""

from __future__ import annotations

from typing import Any

from .lang import language_name
from .payload import fit, humanize

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

STRICT_RETRY = """Your previous answer broke a hard rule ({violations}).
Rewrite it: no absolute reassurance, no claim that the bank is acting on a
transaction, no full card numbers, and no figure that is absent from the JSON.
Keep it factual and short."""


def narrate_prompt(question: str, lang: str, tool: str,
                   result: dict[str, Any]) -> str:
    return NARRATE.format(
        question=question, language=language_name(lang),
        tool=tool, result=fit(humanize(result)),
    )


def strict_retry_prompt(violations: list[str]) -> str:
    return STRICT_RETRY.format(violations=", ".join(violations))
