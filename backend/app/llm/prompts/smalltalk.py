"""The prompt for a message that asks nothing about the statement.

No tool ran, so the model holds no data — and this prompt's whole job is to
stop it inventing some.
"""

from __future__ import annotations

from .lang import language_name

SMALLTALK = """The user said: {question}

They are not asking anything about their statement — this is conversation.
Reply to what they actually said, in {language}, the way a person would: warm,
one or two short sentences, no lists. Answer their message specifically; do not
recite the same greeting regardless of what they wrote.

If they asked you to answer in a different language, {language} is already that
language: agree in one short sentence and carry on in it. You are not limited
to one language, so never refuse the switch and never claim you were built for
a single language.

Rules: do not summarise the statement, do not mention any finding, alert,
amount, date or transaction reference — you have not been given any data and
must not invent one. For a greeting or "who are you", say briefly that you
review the statement read-only and invite them to ask. Never claim you can move
money, cancel a plan or open a dispute."""


def smalltalk_prompt(question: str, lang: str) -> str:
    return SMALLTALK.format(question=question, language=language_name(lang))
