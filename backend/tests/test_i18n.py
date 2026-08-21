"""The wording contract.

Two rules this suite exists to keep:

* User-facing wording lives in `app/i18n/{vi,en}.json`, never in code. Both
  catalogs carry the same keys with the same placeholders, so VI and EN cannot
  drift apart and every placeholder gets filled.
* Prompts live in `app/llm/prompts/` and are written in English only. The
  answer language is a parameter inside the prompt, not a second copy of it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.engine.render import I18N_DIR, LANGS
from app.llm.summarize import summarize
from app.llm.tools import TOOLS, run_tool

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "app" / "llm" / "prompts"
SUMMARIZE_SRC = Path(__file__).resolve().parent.parent / "app" / "llm" / "summarize.py"

PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
# A literal key: t(lang, "summary.error", ...). A key built at runtime —
# t(lang, "cadence." + sub["cadence"]) — is a prefix, checked separately.
STATIC_KEY = re.compile(r"""t\(lang,\s*["']([a-z_.]+)["']\s*[,)]""")
DYNAMIC_PREFIX = re.compile(r"""t\(lang,\s*["']([a-z_.]+\.)["']\s*\+""")
UNFILLED = re.compile(r"\{[a-z_]+\}")

# Typography the prompts may use; anything else non-ASCII means a translated
# prompt has crept in.
PROMPT_PUNCTUATION = set("…—–→₫“”’‘↔")


def catalogs() -> dict[str, dict[str, str]]:
    return {lang: json.loads((I18N_DIR / f"{lang}.json").read_text())
            for lang in LANGS}


def test_every_language_carries_the_same_keys():
    loaded = catalogs()
    reference = set(loaded["vi"])
    for lang, strings in loaded.items():
        assert set(strings) == reference, (
            f"{lang}.json differs by {set(strings) ^ reference}")


def test_a_key_takes_the_same_placeholders_in_every_language():
    loaded = catalogs()
    for key in loaded["vi"]:
        expected = PLACEHOLDER.findall(loaded["vi"][key])
        for lang, strings in loaded.items():
            assert set(PLACEHOLDER.findall(strings[key])) == set(expected), (
                f"{lang}.json:{key} placeholders differ from vi.json")


def test_every_key_the_summaries_ask_for_exists():
    keys = set(STATIC_KEY.findall(SUMMARIZE_SRC.read_text()))
    assert keys, "no i18n keys found — did summarize.py stop using t()?"
    loaded = catalogs()
    for lang, strings in loaded.items():
        missing = sorted(k for k in keys if k not in strings)
        assert missing == [], f"{lang}.json has no entry for {missing}"


def test_every_runtime_built_key_has_a_family_to_build_from():
    """`t(lang, "cadence." + value)` needs the whole `cadence.*` family."""
    prefixes = set(DYNAMIC_PREFIX.findall(SUMMARIZE_SRC.read_text()))
    assert prefixes, "no runtime-built keys found — check the regex"
    loaded = catalogs()
    for lang, strings in loaded.items():
        for prefix in prefixes:
            assert any(k.startswith(prefix) for k in strings), (
                f"{lang}.json has no {prefix}* entries")


def test_no_summary_wording_is_hardcoded_in_the_summaries():
    """A `if vi else` branch is the shape this refactor removed. Keep it out."""
    source = SUMMARIZE_SRC.read_text()
    assert "if vi else" not in source
    assert 'lang == "vi"' not in source


TOOL_ARGS = {
    "explain_charge": {"ref": "CRD-0041"},
    "get_cancellation_guide": {"merchant": "Netflix"},
}


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("tool", sorted(TOOLS))
def test_every_summary_fills_every_placeholder(tool, lang):
    result = run_tool(tool, dict(TOOL_ARGS.get(tool, {})), lang)
    text = summarize(tool, result, lang)
    assert text.strip(), f"{tool} produced no summary in {lang}"
    left = UNFILLED.findall(text)
    assert left == [], f"{tool} [{lang}] left {left} unfilled"


@pytest.mark.parametrize("lang", LANGS)
def test_an_unknown_tool_still_answers(lang):
    assert summarize("no_such_tool", {}, lang).strip()


def test_prompts_are_written_in_english_only():
    for path in sorted(PROMPTS_DIR.glob("*.py")):
        stray = {c for c in path.read_text()
                 if ord(c) > 127 and c not in PROMPT_PUNCTUATION}
        assert stray == set(), (
            f"{path.name} contains non-English text ({sorted(stray)}); "
            "prompts stay English and take the answer language as a parameter")


def test_prompt_families_each_live_in_their_own_file():
    from app.llm import prompts

    assert prompts.system_prompt.__module__ == "app.llm.prompts.system"
    assert prompts.router_prompt.__module__ == "app.llm.prompts.router"
    assert prompts.narrate_prompt.__module__ == "app.llm.prompts.narrate"
    assert prompts.smalltalk_prompt.__module__ == "app.llm.prompts.smalltalk"
    assert prompts.humanize.__module__ == "app.llm.prompts.payload"


def test_the_answer_language_is_a_prompt_parameter():
    from app.llm import prompts

    labels = {"recurring_confirmed": "R", "needs_your_confirmation": "N",
              "insufficient_data": "I"}
    assert "in Vietnamese" in prompts.system_prompt("vi", labels)
    assert "in English" in prompts.system_prompt("en", labels)
    # One template, two languages: the rest of the prompt is identical.
    vi = prompts.system_prompt("vi", labels).replace("Vietnamese", "")
    en = prompts.system_prompt("en", labels).replace("English", "")
    assert vi == en
