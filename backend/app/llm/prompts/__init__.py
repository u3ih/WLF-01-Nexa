"""Every prompt the model is ever shown, one file per prompt family.

    lang      — language code -> language name, the only place it is decided
    system    — who the model is and the rules it cannot argue with
    router    — pick one read-only tool, or none (JSON mode and native mode)
    narrate   — turn one tool result into prose, plus the post-breach retry
    smalltalk — reply to a message that asks nothing about the statement
    payload   — make a tool result safe and small enough to put in a prompt

Every prompt is written in English, including the ones that must produce a
Vietnamese answer: the output language is a `{language}` parameter, never a
second copy of the text. User-facing wording lives in `app/i18n/*.json`
instead — see `app.engine.render.t`.

Import through this module (`from . import prompts`); the submodule layout is
free to change behind it.
"""

from __future__ import annotations

from .lang import LANG_NAME, language_name
from .narrate import (CONTINUE, NARRATE, STRICT_RETRY, narrate_prompt,
                      strict_retry_prompt)
from .payload import PAYLOAD_BUDGET, fit, humanize
from .router import (ROUTER, TEMPORAL, TOOL_CHOICE, native_tool_schemas,
                     router_prompt, temporal_note, tool_list_text)
from .smalltalk import SMALLTALK, smalltalk_prompt
from .system import SYSTEM, system_prompt

__all__ = [
    "LANG_NAME", "language_name",
    "SYSTEM", "system_prompt",
    "TOOL_CHOICE", "ROUTER", "router_prompt", "tool_list_text",
    "native_tool_schemas", "TEMPORAL", "temporal_note",
    "NARRATE", "narrate_prompt", "STRICT_RETRY", "strict_retry_prompt",
    "CONTINUE",
    "SMALLTALK", "smalltalk_prompt",
    "humanize", "fit", "PAYLOAD_BUDGET",
]
