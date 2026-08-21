"""The one place that maps a UI language code to a name the model understands.

Prompts are written in English; only the *answer* has to come back in the
user's language. So the language never forks the prompt text — it is a
parameter inside it.
"""

from __future__ import annotations

LANG_NAME = {"vi": "Vietnamese", "en": "English"}
DEFAULT_LANG_NAME = "Vietnamese"


def language_name(lang: str) -> str:
    return LANG_NAME.get(lang, DEFAULT_LANG_NAME)
