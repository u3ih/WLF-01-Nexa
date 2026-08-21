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

State which period the JSON is about, taken from its own `period` field. If the
JSON carries a `coverage` block with "has_data": false, say plainly that the
data does not cover the period asked about and name the range it does cover —
do not report that period's zeros as amounts.

Write the answer in {language}. Rules: use only figures present in the JSON;
keep the label wording from the JSON; quote transaction references; include the
dispute deadline text when the JSON has one; never say the account is safe or
that nothing is unusual; never claim you performed any action. If the JSON does
not answer the question, say that the data does not contain it."""

CONTINUE = """Your answer stopped at the output limit, mid-way. Continue it from
exactly where it stopped — carry on the sentence, row or section you were in.
Do not repeat anything already written, do not restate the question and do not
open with a preamble. Same rules as before: only figures present in the JSON.
Finish the answer, then stop."""

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
