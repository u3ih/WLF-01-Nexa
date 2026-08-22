"""Chat orchestration: guardrail -> route -> read-only tool -> narrate -> verify.

The model never sees the raw dataset, only a tool result. Its prose is then
checked twice: once for banned wording, once for figures that do not appear in
the tool result. Failing either check, the deterministic summary is sent
instead — so the reply can be wrong-sounding but never wrong-numbered.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from ..config import settings
from ..engine import pipeline
from ..engine.render import disclaimer, fx_block, normalise_lang, t
from ..store import store
from . import guardrails, prompts, smalltalk, summarize
from .detect import detect_lang, requested_lang
from .client import (CHAT_ONLY, REF_PATTERN, ToolCall, client, extract_args,
                     keyword_route)
from .tools import ALLOWED_ARGS, run_tool

MONEY_IN_TEXT = re.compile(r"\$\s?\d[\d,]*(?:\.\d{2})?")
# Case-sensitive on purpose. References are uppercase everywhere in the data,
# and the pattern is wide enough that a case-insensitive match would read
# ordinary lowercase prose as a reference and flag a grounded reply.
REF_IN_TEXT = re.compile(rf"\b{REF_PATTERN}\b")
VND_IN_TEXT = re.compile(r"[\d][\d.]*\s?₫")


def _labels(lang: str) -> dict[str, str]:
    return {
        "recurring_confirmed": t(lang, "labels.recurring_confirmed"),
        "needs_your_confirmation": t(lang, "labels.needs_your_confirmation"),
        "insufficient_data": t(lang, "labels.insufficient_data"),
    }


def _numbers_grounded(text: str, payload: str) -> list[str]:
    """Figures and transaction references in the reply that the tool result
    does not contain.

    Catches both an invented amount and a mistyped reference (an ACC- row
    reported as CRD-, for instance), which is the failure mode a purely
    numeric check misses.
    """
    haystack = payload.replace(",", "")
    missing = []
    for raw in MONEY_IN_TEXT.findall(text):
        normalised = raw.replace("$", "").replace(" ", "").replace(",", "")
        if normalised and normalised not in haystack:
            missing.append(raw)
    for raw in VND_IN_TEXT.findall(text):
        normalised = raw.replace(" ", "")
        if normalised not in payload.replace(" ", ""):
            missing.append(raw)
    upper_haystack = haystack.upper()
    for ref in REF_IN_TEXT.findall(text):
        if ref.upper() not in upper_haystack:
            missing.append(ref.upper())
    return missing


def _refusal_payload(lang: str, verdict: guardrails.IntentVerdict,
                     today: date) -> dict[str, Any]:
    """Build the reply for a request we are not allowed to carry out."""
    analysis = pipeline.cached()
    labels = analysis.summary(lang, today)["labels"]
    intent = verdict.intent
    text = t(lang, f"refusal.{intent.value}",
             needs_confirmation=labels["needs_your_confirmation"],
             insufficient_data=labels["insufficient_data"])
    tools_used: list[str] = []
    extra: dict[str, Any] = {}

    if intent is guardrails.BlockedIntent.CANCEL_SUBSCRIPTION:
        # A "how do I cancel" request is legitimate: hand over the steps, and
        # make clear we are not performing them.
        args = extract_args(verdict.matched)
        result = run_tool("get_cancellation_guide",
                          {"merchant": args.get("merchant")}, lang)
        tools_used.append("get_cancellation_guide")
        extra["data"] = result
        text = f"{text}\n\n{summarize.summarize('get_cancellation_guide', result, lang)}"
    elif intent is guardrails.BlockedIntent.DISPUTE:
        # We cannot file it, but we can hand over the evidence they will need.
        result = run_tool("get_findings", {"label": "needs_your_confirmation"}, lang)
        tools_used.append("get_findings")
        extra["data"] = result
        text = f"{text}\n\n{summarize.summarize('get_findings', result, lang)}"
    else:
        text = f"{text} {t(lang, 'refusal.suffix')}"

    return {"text": text, "tools_used": tools_used, **extra}


def _smalltalk_reply(question: str, lang: str, labels: dict[str, str],
                     base: dict[str, Any], routed_by: str) -> dict[str, Any]:
    """Answer a message that asks nothing about the statement.

    No tool ran, so the model has no grounded figure to cite — which makes the
    grounding check absolute here: any number at all is invented, and the reply
    falls back to a fixed line.
    """
    kind = smalltalk.classify(question)
    canned = t(lang, f"smalltalk.{kind.value}" if kind else "smalltalk.greeting")

    text = client.chat_smalltalk(question, lang, labels)
    source = "llm"
    if text:
        review = guardrails.check_output(text)
        if review.violations or _numbers_grounded(review.text, ""):
            text, source = canned, "smalltalk_canned"
        else:
            text = review.text
    else:
        text = canned
        source = ("llm_unavailable" if not client.status().available
                  else "smalltalk_canned")

    store.log("chat_smalltalk", reason=question[:200],
              detail={"lang": lang, "routed_by": routed_by, "source": source})
    return {**base, "answer": guardrails.check_output(text).text,
            "tool": None, "tools_used": [], "tool_args": {},
            "routed_by": routed_by, "data": None, "refused": False,
            "source": source, "checks": {}, "smalltalk": True}


def resolve_lang(question: str, ui_lang: str,
                 held: str | None = None) -> tuple[str, str | None]:
    """The language to answer in, and the one to keep answering in.

    Three signals, in the order a person would read them:

    1. What the user asked for. "Trả lời bằng tiếng Anh" is a Vietnamese
       sentence requesting English, so an instruction always outranks the
       language it was written in.
    2. What they asked for earlier. The endpoint is stateless, so the caller
       hands that back as `held` and it survives until they ask for something
       else — otherwise "from now on, English" lasts exactly one turn.
    3. Failing both, the language of this message, and then the UI toggle.

    The second return value is what the caller should hand back next turn:
    None while nobody has asked for anything, so plain detection keeps working.
    """
    asked = requested_lang(question)
    held = normalise_lang(held) if held else None
    if asked:
        return asked, asked
    if held:
        return held, held
    return detect_lang(question, ui_lang), None


def answer(question: str, lang: str = "vi", today: date | None = None,
           reply_lang: str | None = None) -> dict[str, Any]:
    # The toggle says which language the UI is in; the question says which
    # language the user is speaking, and an explicit request outranks both.
    # Whatever wins applies to the whole reply, so the prose, the labels and
    # the rendered tool result cannot come back in two languages at once.
    ui_lang = normalise_lang(lang)
    lang, held_lang = resolve_lang(question, ui_lang, reply_lang)
    today = today or settings.today()
    labels = _labels(lang)
    status = client.status()
    verdict = guardrails.classify_intent(question)

    store.log("chat_question", reason=question[:300],
              detail={"lang": lang, "ui_lang": ui_lang,
                      "reply_lang": held_lang,
                      "guardrail": guardrails.describe(verdict),
                      "llm_mode": status.mode})

    base = {
        "lang": lang,
        "ui_lang": ui_lang,
        # Handed back so the next question keeps the language the user asked
        # for, whatever language they happen to type it in.
        "reply_lang": held_lang,
        "question": question,
        "guardrail": guardrails.describe(verdict),
        "llm": status.as_dict(),
        "labels": labels,
        "disclaimer": disclaimer(lang),
        "fx": fx_block(lang),
        "statement_date": pipeline.cached().ds.meta.get("statement_date"),
        "generated_for": today.isoformat(),
    }

    # ---- refused up front: no tool that could act on money is ever reachable
    if verdict.blocked and verdict.severity is guardrails.Severity.HARD:
        payload = _refusal_payload(lang, verdict, today)
        store.log("request_refused", kind=verdict.intent.value,
                  reason=f"blocked intent: {verdict.intent.value}",
                  detail={"matched": verdict.matched, "lang": lang})
        return {**base, "answer": payload["text"], "tool": None,
                "tools_used": payload["tools_used"],
                "data": payload.get("data"), "refused": True,
                "source": "guardrail"}

    # ---- reassurance: refuse the framing, then show the evidence anyway
    prefix = ""
    if verdict.blocked and verdict.severity is guardrails.Severity.SOFT:
        analysis_labels = pipeline.cached().summary(lang, today)["labels"]
        prefix = t(lang, "refusal.reassurance",
                   needs_confirmation=analysis_labels["needs_your_confirmation"],
                   insufficient_data=analysis_labels["insufficient_data"])
        call = ToolCall("get_findings", {}, "guardrail")
    else:
        call = client.route(question, lang, labels)

    # ---- the model judged that no statement data is needed: converse
    if call.name == CHAT_ONLY:
        return _smalltalk_reply(question, lang, labels, base, call.chosen_by)

    result = run_tool(call.name, call.args, lang)
    # Ground the reply against exactly what the model was shown.
    payload = json.dumps(prompts.humanize(result), ensure_ascii=False,
                         default=str)
    deterministic = summarize.summarize(call.name, result, lang)

    text = client.narrate(question, lang, labels, call.name, result)
    source = "llm"
    checks: dict[str, Any] = {}

    if text:
        review = guardrails.check_output(text)
        ungrounded = _numbers_grounded(review.text, payload)
        checks = {"violations": review.violations, "ungrounded_numbers": ungrounded}
        if review.violations or ungrounded:
            retry = client.narrate(
                question, lang, labels, call.name, result,
                retry_violations=review.violations
                + [f"invented figure {n}" for n in ungrounded],
            )
            if retry:
                second = guardrails.check_output(retry)
                second_ungrounded = _numbers_grounded(second.text, payload)
                checks["retry"] = {"violations": second.violations,
                                   "ungrounded_numbers": second_ungrounded}
                if not second.violations and not second_ungrounded:
                    text, source = second.text, "llm_retry"
                else:
                    text, source = deterministic, "deterministic_fallback"
            else:
                text, source = deterministic, "deterministic_fallback"
        else:
            text = review.text
    else:
        # The model produced nothing. Say which kind of nothing: a configured
        # outage reads differently from a model that is up but failed on this
        # request, and in an AI product that difference is worth surfacing.
        source = "llm_unavailable" if not client.status().available else "llm_error"
        text = deterministic

    if source.startswith(("deterministic", "llm_error")) and checks:
        store.log("llm_output_rejected", reason=json.dumps(checks)[:400],
                  detail={"tool": call.name, "lang": lang})
    if source in ("llm_unavailable", "llm_error"):
        store.log("llm_unavailable", reason=client.status().detail[:300],
                  detail={"tool": call.name, "lang": lang, "source": source})

    final = f"{prefix}\n\n{text}".strip() if prefix else text
    # Final safety net: the reply that leaves the process is always scrubbed.
    final = guardrails.check_output(final).text

    return {
        **base,
        "answer": final,
        "tool": call.name,
        "tools_used": [call.name],
        "tool_args": call.args,
        "routed_by": call.chosen_by,
        "data": result,
        "refused": False,
        "source": source,
        "checks": checks,
    }
