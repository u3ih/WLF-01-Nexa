"""Model client. Which provider it talks to is decided by the environment.

Two transports are implemented and both are reachable purely from `.env`:

* **ollama** — a local Ollama daemon (`/api/tags`, `/api/chat`, `/api/show`).
* **openai** — any OpenAI-compatible endpoint (`/models`, `/chat/completions`),
  which covers hosted gateways such as BytePlus Ark, OpenAI itself, Groq,
  Together, vLLM and llama.cpp's server.

`NEXA_AI_PROVIDER` picks one; the default `auto` sniffs the URL and the presence
of an API key, then falls back to probing the other transport. Whichever answers
is normalised into the same reply shape, so the rest of this module — and all of
`chat.py` — is provider-agnostic.

On top of that sits the tier the assistant reports under every answer:

1. native_tools — the model advertises (or accepts) tool calling.
2. json_router  — any chat model; it returns {"tool": ..., "args": ...} as JSON.
3. offline      — no model reachable; a keyword router picks the tool and the
                  answer is composed deterministically from engine output.

The demo therefore works with a hosted model, with a local one, or with none.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..config import settings
from ..engine import reports
from . import prompts, smalltalk
from .tools import ALLOWED_ARGS, TOOLS, data_coverage

JSON_BLOCK = re.compile(r"\{.*\}", re.S)
STATUS_TTL_SECONDS = 30.0
DOWN_STATUS_TTL_SECONDS = 3.0

# Tier-3 router. Order matters: the first pattern that matches wins.
KEYWORD_ROUTES: list[tuple[str, str]] = [
    (r"(gửi|soạn).{0,25}(báo cáo).{0,25}(email|mail)|email me the report|"
     r"send .{0,20}report", "draft_report_email"),
    (r"(huỷ|hủy).{0,20}(thế nào|làm sao|cách|các bước)|"
     r"(làm sao|làm thế nào|cách|các bước).{0,20}(huỷ|hủy)|"
     r"how (do|can) i cancel|cancel.{0,15}steps", "get_cancellation_guide"),
    # An explicit "what is this <amount|reference>" outranks the email table,
    # because explain_charge already reports the email match for that charge.
    (r"(là gì|nghĩa là gì|of what|what is|what'?s|giải thích).{0,40}"
     r"((\$|usd)\s?\d|\d+[.,]\d{2}|(acc|crd)-\d+)|"
     r"((\$|usd)\s?\d|\d+[.,]\d{2}|(acc|crd)-\d+).{0,40}(là gì|what is|what'?s)",
     "explain_charge"),
    (r"nhắc hạn|hạn khiếu nại|reminder|deadline", "get_reminders"),
    (r"rà soát lại|quét lại|kiểm tra lại|có gì mới|check again|scan again|r?e-?scan|any new|new (issues?|findings?|alerts?)",
     "run_monitor_scan"),
    (r"nhật ký|audit|journal|log", "get_audit_log"),
    (r"chưa (thấy )?lên thẻ|chưa vào thẻ|rời tài khoản|số dư ví|ví.{0,10}lệch|"
     r"nạp trùng|wallet|not on (the )?card|duplicate deposit|three source|3 nguồn",
     "get_tri_source"),
    (r"gói|định kỳ|đăng ký|thuê bao|tăng giá|subscription|recurring|price "
     r"(increase|rise|went up)", "list_subscriptions"),
    # Impersonation wording ahead of the generic email route: the same tool
    # answers it, but this also catches the question when the word "email" is
    # never typed ("có ai giả danh Netflix không").
    (r"lừa đảo|giả danh|mạo danh|giả mạo|email giả|phishing|fake email|"
     r"impersonat|spoof|scam", "get_email_recon"),
    (r"email|biên lai|hoá đơn|hóa đơn|receipt|confirmation|xác nhận",
     "get_email_recon"),
    (r"trùng|hai lần|2 lần|phí kép|duplicate|twice|double.{0,10}(charge|fee)|"
     r"charged.{0,10}twice", "get_findings:duplicates"),
    (r"bất thường|đáng ngờ|khoản lạ|giao dịch lạ|unusual|suspicious|anomal",
     "get_findings"),
    (r"báo cáo|chi (bao nhiêu|tiêu)|tổng chi|phí bao nhiêu|tháng này|quý|năm nay|"
     r"report|how much did i spend|fees|this month|quarter|this year",
     "get_report"),
    (r"(\$|usd)\s?\d|\d+[.,]\d{2}|khoản này là gì|là gì|what is|what.{0,10}charge|"
     r"giải thích|explain", "explain_charge"),
    (r"tìm|liệt kê|danh sách|search|list|show me", "search_transactions"),
]

DEFAULT_TOOL = "get_overview"

# Not a tool: the routing outcome "this message needs no data at all". The model
# picks it by declining to call a tool (native) or by naming it (JSON router),
# so greetings, thanks and "what are you" are recognised by meaning rather than
# by a phrase list.
CHAT_ONLY = "chat_only"

# Argument presets for question shapes where a narrower result reads better.
ARG_PRESETS: dict[str, dict[str, Any]] = {
    "duplicates": {"kind": "duplicate_charge,double_fee,duplicate_payin"},
}

AMOUNT_IN_TEXT = re.compile(r"(?<![\d.])(\d{1,6}[.,]\d{2})(?![\d])")
REF_IN_TEXT = re.compile(r"\b((?:ACC|CRD)-\d{3,5})\b", re.I)

# Period phrasings a person actually types. The model resolves these when one is
# reachable; these patterns are the offline fallback, and the shape check on
# what the model returned.
MONTH_ISO = re.compile(r"\b(20\d{2})[-/](1[0-2]|0?[1-9])\b")
QUARTER_ISO = re.compile(r"\b(20\d{2})[-\s]?Q([1-4])\b", re.I)
YEAR_ISO = re.compile(r"\b(20\d{2})\b")
# "tháng 7/2026", "T7/2026", "7/2026" — the year is stated, so no default is
# needed. Ordered before the bare-month pattern, which would drop it.
MONTH_WITH_YEAR = re.compile(
    r"\b(?:th[áa]ng|month|t)?\s*(1[0-2]|0?[1-9])\s*[/-]\s*(20\d{2})\b", re.I)
MONTH_VI = re.compile(r"\bth[áa]ng\s*(1[0-2]|0?[1-9])\b|\bt(1[0-2]|[1-9])\b", re.I)
# The preposition group is what makes "may" usable: bare "may" is the English
# verb far more often than the month, so it counts only when a year or a
# preposition marks it as a date.
MONTH_EN = re.compile(
    r"\b(in|for|of|during)?\s*(january|february|march|april|may|june|july|"
    r"august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|"
    r"sept|sep|oct|nov|dec)\b\.?\s*(20\d{2})?", re.I)
QUARTER_TEXT = re.compile(r"\b(?:qu[ýy]|quarter|q)\s*([1-4])\b(?:\D{0,10}(20\d{2}))?",
                          re.I)
WHOLE_YEAR = re.compile(r"n[ăa]m nay|c[ải] n[ăa]m|n[ăa]m\s*20\d{2}|this year|"
                        r"whole year|full year|year\s*20\d{2}", re.I)
MONTH_ORDER = ["jan", "feb", "mar", "apr", "may", "jun",
               "jul", "aug", "sep", "oct", "nov", "dec"]

# URL shapes that only an OpenAI-compatible endpoint has. Ollama exposes its own
# API under /api/… with no version segment, so these never collide with it.
OPENAI_URL_HINTS = re.compile(
    r"/v\d+/?$|/api/v[23]/?$|openai|bytepluses|volces|groq|together|deepseek|"
    r"anthropic|mistral|fireworks|openrouter|azure",
    re.I,
)


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    chosen_by: str = "keyword"


@dataclass
class LLMStatus:
    mode: str                      # native_tools | json_router | offline
    model: str
    available: bool
    detail: str = ""
    checked_at: float = 0.0
    provider: str = ""             # ollama | openai | "" when offline

    def as_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "model": self.model,
                "available": self.available, "detail": self.detail,
                "provider": self.provider}


class ToolsUnsupported(RuntimeError):
    """The endpoint rejected the tool schema, so this model cannot call tools."""


def keyword_route(question: str) -> ToolCall:
    """Deterministic routing. Also used to sanity-check the model's choice."""
    text = question.lower()
    args = extract_args(question)
    for pattern, tool in KEYWORD_ROUTES:
        if not re.search(pattern, text, re.I):
            continue
        # "tool:preset" narrows the tool's arguments for a known question shape.
        tool, _, preset = tool.partition(":")
        allowed = ALLOWED_ARGS.get(tool, set())
        call_args = {k: v for k, v in args.items() if k in allowed}
        if preset in ARG_PRESETS:
            call_args.update(ARG_PRESETS[preset])
        return ToolCall(tool, call_args, "keyword")
    return ToolCall(DEFAULT_TOOL, {}, "keyword")


def data_year() -> int:
    """The year the loaded export ends in.

    A month named without one — "tháng 7" — has to resolve against the data,
    not against the wall clock: the two disagree the moment the sample export
    stops being this year's.
    """
    try:
        return int(data_coverage()["latest_month"][:4])
    except Exception:                                   # noqa: BLE001
        return settings.today().year


def period_from_text(question: str,
                     default_year: int | None = None) -> tuple[str, str | None]:
    """The period a question names: ('month'|'quarter'|'year', key or None).

    Only the wording is read here. `None` means the question named no period,
    which the report tool then reads as its latest month.
    """
    year = default_year or data_year()

    iso_quarter = QUARTER_ISO.search(question)
    if iso_quarter:
        return "quarter", f"{iso_quarter.group(1)}-Q{iso_quarter.group(2)}"
    iso_month = MONTH_ISO.search(question)
    if iso_month:
        return "month", f"{iso_month.group(1)}-{int(iso_month.group(2)):02d}"
    with_year = MONTH_WITH_YEAR.search(question)
    if with_year:
        return "month", f"{with_year.group(2)}-{int(with_year.group(1)):02d}"

    # A year stated anywhere else in the sentence still belongs to the month or
    # quarter named in it: "tháng 12 năm 2025" puts the two in separate words.
    loose = YEAR_ISO.search(question)
    stated = loose.group(1) if loose else None

    quarter = QUARTER_TEXT.search(question)
    if quarter:
        return "quarter", f"{quarter.group(2) or stated or year}-Q{quarter.group(1)}"

    vi_month = MONTH_VI.search(question)
    if vi_month:
        month = int(vi_month.group(1) or vi_month.group(2))
        return "month", f"{stated or year}-{month:02d}"
    en_month = MONTH_EN.search(question)
    if en_month:
        name = en_month.group(2).lower()[:3]
        # "may" without a year or a preposition is the verb, not the month.
        if name != "may" or en_month.group(3) or en_month.group(1):
            return "month", (f"{en_month.group(3) or stated or year}"
                             f"-{MONTH_ORDER.index(name) + 1:02d}")

    if WHOLE_YEAR.search(question):
        return "year", stated or str(year)
    if stated:
        return "year", stated
    return "month", None


def valid_period_key(key: str) -> bool:
    """Whether `reports.parse_period_key` can read this key.

    A key it cannot read is not an error there — it silently falls back to the
    latest period, which is exactly the failure this whole path exists to stop.
    So an unreadable key is rejected here, where something else can supply one.
    """
    return bool(MONTH_ISO.fullmatch(key) or QUARTER_ISO.fullmatch(key)
                or YEAR_ISO.fullmatch(key))


def extract_args(question: str) -> dict[str, Any]:
    """Pull an amount, a reference, a period or a merchant out of the question."""
    args: dict[str, Any] = {}
    ref = REF_IN_TEXT.search(question)
    if ref:
        args["ref"] = ref.group(1).upper()
    amount = AMOUNT_IN_TEXT.search(question)
    if amount:
        args["amount"] = float(amount.group(1).replace(",", "."))
    lowered = question.lower()
    kind, key = period_from_text(question)
    args["period"] = kind
    if key:
        args["key"] = key
        # The same period as a date range, for the tools that take one. A
        # listing asked for "in July" that quietly spans every month is the
        # same failure as a report that quietly covers the wrong one.
        bounds = reports.parse_period_key(kind, key, settings.today())
        args["date_from"] = bounds.start.isoformat()
        args["date_to"] = bounds.end.isoformat()
    for merchant in ("netflix", "spotify", "chegg", "apple", "icloud",
                     "t-mobile", "tmobile"):
        if merchant in lowered:
            args["merchant"] = merchant
            args["query"] = merchant
            break
    return args


# --------------------------------------------------------------- transports

def _base_url() -> str:
    return settings.ai_url.rstrip("/")


def _request(method: str, path: str, payload: dict[str, Any] | None = None,
             headers: dict[str, str] | None = None,
             timeout: float | None = None) -> dict[str, Any]:
    """One HTTP call to the model, retrying transport failures.

    A dropped connection or a model still loading into memory is a blip, not an
    outage; retrying here is what keeps a live model from being written off
    after one unlucky request. A 4xx is our own bug — bad key, wrong model,
    unsupported field — and is raised immediately so the caller can say so.
    """
    url = f"{_base_url()}{path}"
    attempts = max(1, settings.ai_retries + 1)
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with httpx.Client(
                    timeout=timeout or settings.llm_timeout_seconds) as http:
                response = (http.get(url, headers=headers) if method == "GET"
                            else http.post(url, json=payload, headers=headers))
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500:
                raise
            last = exc
        except Exception as exc:                        # noqa: BLE001
            last = exc
        if attempt + 1 < attempts:
            time.sleep(settings.ai_retry_backoff_seconds * (attempt + 1))
    raise last                                          # type: ignore[misc]


class OllamaBackend:
    """A local Ollama daemon."""

    name = "ollama"

    def list_models(self) -> list[str]:
        tags = _request("GET", "/api/tags", timeout=5.0)
        return [m["model"] for m in tags.get("models", [])]

    def supports_tools(self, model: str) -> bool:
        try:
            info = _request("POST", "/api/show", {"model": model}, timeout=10.0)
        except Exception:                               # noqa: BLE001
            return False
        return "tools" in (info.get("capabilities") or [])

    def chat(self, model: str, messages: list[dict[str, Any]],
             tools: list[dict[str, Any]] | None, num_predict: int
             ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            # Reasoning models otherwise spend the whole budget on `thinking`
            # and return a truncated answer.
            "think": False,
            "options": {"temperature": 0, "num_predict": num_predict},
        }
        if tools:
            payload["tools"] = tools
        try:
            return self._normalise(_request("POST", "/api/chat", payload))
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 400:
                raise
            if tools:
                raise ToolsUnsupported(_error_text(exc)) from exc
            # Older Ollama builds, or non-thinking models, reject "think".
            payload.pop("think", None)
            return self._normalise(_request("POST", "/api/chat", payload))

    @staticmethod
    def _normalise(data: dict[str, Any]) -> dict[str, Any]:
        """Carry the stop reason alongside the message.

        Ollama names it `done_reason`, and "length" there means the same thing
        as OpenAI's "length": the answer was cut off at the cap, not finished.
        """
        message = dict(data.get("message") or {})
        message["finish_reason"] = data.get("done_reason") or ""
        return {**data, "message": message}


class OpenAIBackend:
    """Any OpenAI-compatible endpoint: Ark, OpenAI, Groq, vLLM, llama.cpp…"""

    name = "openai"

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        key = settings.ai_api_key.strip()
        if key:
            headers["authorization"] = f"Bearer {key}"
        return headers

    def list_models(self) -> list[str]:
        data = _request("GET", "/models", headers=self._headers(), timeout=8.0)
        items = data.get("data") if isinstance(data, dict) else None
        return [m.get("id", "") for m in (items or []) if m.get("id")]

    def supports_tools(self, model: str) -> bool:
        """No endpoint advertises this, so it is a declaration rather than a
        probe: `auto` assumes yes, and a rejected tool schema downgrades the
        tier at runtime instead of costing a wasted request here."""
        setting = settings.ai_native_tools.strip().lower()
        if setting in ("true", "1", "yes", "on"):
            return True
        if setting in ("false", "0", "no", "off"):
            return False
        return True

    def chat(self, model: str, messages: list[dict[str, Any]],
             tools: list[dict[str, Any]] | None, num_predict: int
             ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "temperature": 0,
            "max_tokens": num_predict,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        try:
            data = _request("POST", "/chat/completions", payload,
                            headers=self._headers())
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 400:
                raise
            text = _error_text(exc)
            # Newer APIs renamed the output cap; older ones only know the old
            # name. Which one this endpoint wants is not worth a config flag.
            if "max_completion_tokens" in text:
                payload.pop("max_tokens", None)
                payload["max_completion_tokens"] = num_predict
                data = _request("POST", "/chat/completions", payload,
                                headers=self._headers())
            elif tools:
                raise ToolsUnsupported(text) from exc
            elif "temperature" in text:
                # Some reasoning models accept only their own default.
                payload.pop("temperature", None)
                data = _request("POST", "/chat/completions", payload,
                                headers=self._headers())
            else:
                raise
        return self._normalise(data)

    @staticmethod
    def _normalise(data: dict[str, Any]) -> dict[str, Any]:
        """Reshape a completion into the {"message": …} form this module reads,
        so neither the router nor the narrator knows which provider replied."""
        choices = data.get("choices") or []
        message = (choices[0].get("message") or {}) if choices else {}
        calls = []
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            calls.append({"function": {
                "name": function.get("name", ""),
                "arguments": function.get("arguments") or {},
            }})
        return {"message": {"content": message.get("content") or "",
                            "tool_calls": calls,
                            # "length" means the cap stopped the answer. The
                            # narrator reads this to continue instead of
                            # returning a reply cut off mid-sentence.
                            "finish_reason": (choices[0].get("finish_reason")
                                              if choices else "") or ""}}


def _join_continuation(head: str, tail: str) -> str:
    """Stitch a continued answer back to the part that was cut off.

    Where the cap fell decides the seam. After a finished sentence or table row
    the continuation is a new block, so it gets a blank line. Cut mid-sentence —
    or mid-row, or mid-word — it is the rest of that line and must not have a
    line break pushed into it, or the table breaks and the sentence reads as two.
    """
    if not head:
        return tail.strip()
    if head[-1] in ".!?:;\n" or head.endswith("|"):
        return f"{head}\n\n{tail.lstrip()}"
    return head + tail


def _error_text(exc: httpx.HTTPStatusError) -> str:
    try:
        return exc.response.text[:400]
    except Exception:                                   # noqa: BLE001
        return str(exc)


def _describe_http_error(exc: Exception, backend: str) -> str:
    """Turn a failed probe into a sentence an operator can act on."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            if backend == "openai":
                return (f"HTTP {code}, authentication rejected — set "
                        f"NEXA_AI_API_KEY for this endpoint")
            return (f"HTTP {code} — this URL is a gated API, not an Ollama "
                    f"daemon")
        if code == 404:
            if backend == "openai":
                return ("HTTP 404 on /models — check NEXA_AI_URL includes the "
                        "API base path, e.g. /v1")
            return "HTTP 404 on /api/tags — not an Ollama daemon"
        return f"HTTP {code}"
    return f"{type(exc).__name__}"


class AIClient:
    def __init__(self) -> None:
        self._status: LLMStatus | None = None
        self._backend: OllamaBackend | OpenAIBackend | None = None
        # Set when an endpoint rejects the tool schema, so the tier drops to
        # json_router for the rest of the process instead of retrying forever.
        self._tools_rejected = False

    # -- provider selection -----------------------------------------------

    @staticmethod
    def _candidates() -> list[OllamaBackend | OpenAIBackend]:
        """Which transports to try, in order.

        `auto` reads the two things that actually distinguish the setups: a
        versioned URL path or a configured API key means a hosted
        OpenAI-compatible endpoint; a bare host means a local Ollama.
        """
        choice = settings.ai_provider.strip().lower()
        if choice in ("ollama", "local"):
            return [OllamaBackend()]
        if choice in ("openai", "openai-compatible", "compatible", "ark",
                      "byteplus", "cloud"):
            return [OpenAIBackend()]
        looks_openai = bool(OPENAI_URL_HINTS.search(settings.ai_url)
                            or settings.ai_api_key.strip())
        return ([OpenAIBackend(), OllamaBackend()] if looks_openai
                else [OllamaBackend(), OpenAIBackend()])

    # -- transport --------------------------------------------------------

    def _chat(self, messages: list[dict[str, Any]],
              tools: list[dict[str, Any]] | None = None,
              num_predict: int = 1200) -> dict[str, Any]:
        status = self.status()
        backend = self._backend or self._candidates()[0]
        try:
            return backend.chat(status.model, messages, tools, num_predict)
        except ToolsUnsupported as exc:
            # Record it so the next turn routes through the JSON router, and
            # report this turn as a failure rather than as "no tool needed".
            self._tools_rejected = True
            if self._status:
                self._status = LLMStatus(
                    "json_router", status.model, True,
                    f"{status.detail}; tool schema rejected by the endpoint, "
                    f"using JSON routing",
                    self._status.checked_at, status.provider,
                )
            raise exc

    # -- capability probe -------------------------------------------------

    def status(self, refresh: bool = False) -> LLMStatus:
        now = time.monotonic()
        if self._status and not refresh:
            # A healthy probe is cached; an unhealthy one is re-checked almost
            # immediately, so the assistant recovers the moment the model is
            # back instead of staying offline for a full cache window.
            ttl = (STATUS_TTL_SECONDS if self._status.available
                   else DOWN_STATUS_TTL_SECONDS)
            if now - self._status.checked_at < ttl:
                return self._status

        if settings.offline_mode:
            self._backend = None
            self._status = LLMStatus("offline", settings.ai_model, False,
                                     "NEXA_OFFLINE_MODE is set", now)
            return self._status

        failures: list[str] = []
        for backend in self._candidates():
            try:
                models = backend.list_models()
            except Exception as exc:                    # noqa: BLE001
                failures.append(
                    f"{backend.name}: {_describe_http_error(exc, backend.name)}")
                continue
            self._backend = backend
            self._status = self._status_for(backend, models, now)
            return self._status

        self._backend = None
        self._status = LLMStatus(
            "offline", settings.ai_model, False,
            f"AI model unreachable at {_base_url()} after "
            f"{settings.ai_retries + 1} attempts ({'; '.join(failures)})",
            now,
        )
        return self._status

    def _status_for(self, backend: OllamaBackend | OpenAIBackend,
                    models: list[str], now: float) -> LLMStatus:
        model = settings.ai_model
        if model in models or not models:
            # An empty listing is a gateway that will not enumerate its models,
            # not proof that ours is missing; the configured name stands.
            detail = f"model '{model}' ready"
        elif backend.name == "ollama":
            alternative = next((m for m in models if "embed" not in m), None)
            detail = (f"model '{model}' is not installed"
                      f"{'; falling back to ' + alternative if alternative else ''}")
            if not alternative:
                return LLMStatus("offline", model, False, detail, now,
                                 backend.name)
            model = alternative
        else:
            # A hosted gateway often serves deployment names it does not list,
            # so this is a warning rather than an outage. If the name really is
            # wrong the first request fails and the answer says the model
            # errored — which is the honest report either way.
            detail = (f"model '{model}' is not in the endpoint's listing; "
                      f"using it anyway")

        supports_tools = (not self._tools_rejected
                          and backend.supports_tools(model))
        return LLMStatus(
            "native_tools" if supports_tools else "json_router",
            model, True,
            f"{backend.name}: {detail}"
            + (", native tool calling" if supports_tools
               else ", JSON routing (no native tool support)"),
            now,
            backend.name,
        )

    # -- routing ----------------------------------------------------------

    def route(self, question: str, lang: str, labels: dict[str, str]) -> ToolCall:
        """Model-first, keyword table second.

        The table reads words; only the model reads meaning, and the difference
        surfaced as a wrong answer rather than a wrong route. "Đọc & phân loại
        sao kê … trong tháng 7" matched the report pattern, so the model was
        never asked — and "tháng 7", which no pattern carried, was dropped. The
        report then covered the latest month and the reply said July was
        missing from a dataset that holds it.

        The table is now what answers when there is no model to ask, and the
        arguments it reads out of the question still fill anything the model
        left unset.
        """
        status = self.status()
        fallback = keyword_route(question)
        if not status.available:
            # No model to read the meaning, so the phrase list is all we have.
            # It is deliberately narrow: it only fires on a bare opener.
            if smalltalk.classify(question):
                return ToolCall(CHAT_ONLY, {}, "keyword")
            return fallback
        try:
            chosen = self._route_with_model(question, lang, labels, fallback)
        except Exception:                               # noqa: BLE001
            return fallback
        return chosen or fallback

    def _route_with_model(self, question: str, lang: str,
                          labels: dict[str, str],
                          fallback: ToolCall) -> ToolCall | None:
        """Ask the model which tool answers this. None means it did not say."""
        status = self.status()
        if status.mode == "native_tools":
            data = self._chat(
                [
                    {"role": "system",
                     "content": prompts.system_prompt(lang, labels)
                     + "\n\n" + prompts.TOOL_CHOICE
                     + "\n\n" + prompts.temporal_note()},
                    {"role": "user", "content": question},
                ],
                tools=prompts.native_tool_schemas(),
                num_predict=300,
            )
            calls = (data.get("message") or {}).get("tool_calls") or []
            if not calls:
                return self._no_tool_chosen("native_tools", fallback)
            function = calls[0].get("function", {})
            name = function.get("name", "")
            raw_args = function.get("arguments") or {}
            if isinstance(raw_args, str):
                raw_args = json.loads(raw_args or "{}")
            if name in TOOLS:
                return ToolCall(name, self._merge_args(name, raw_args, question),
                                "native_tools")
            return None

        messages = [
            {"role": "system", "content": prompts.system_prompt(lang, labels)},
            {"role": "user", "content": prompts.router_prompt(question)},
        ]
        data = self._chat(messages, num_predict=200)
        content = (data.get("message") or {}).get("content", "")
        block = JSON_BLOCK.search(content or "")
        if block:
            parsed = json.loads(block.group(0))
            name = parsed.get("tool", "")
            if name == CHAT_ONLY:
                return self._no_tool_chosen("json_router", fallback)
            if name in TOOLS:
                return ToolCall(name,
                                self._merge_args(name, parsed.get("args") or {},
                                                 question),
                                "json_router")
        return None

    @staticmethod
    def _no_tool_chosen(mode: str, fallback: ToolCall) -> ToolCall:
        """The model read the message as needing no statement data.

        Now that the model is asked first, that judgement arrives for real
        questions too. When the keyword table names a specific tool, the table
        wins: answering "how much did I spend in July" as chit-chat is the
        worse of the two failures.
        """
        if fallback.name != DEFAULT_TOOL:
            return fallback
        return ToolCall(CHAT_ONLY, {}, mode)

    @staticmethod
    def _merge_args(tool: str, raw: dict[str, Any],
                    question: str) -> dict[str, Any]:
        """The model's arguments, filtered, shape-checked and topped up.

        The model owns the period it resolved from the wording — that is the
        whole reason it is asked. What the question states literally still fills
        anything the model left out, and a period key in a shape the engine
        cannot parse is dropped, so the shape read from the question takes over
        rather than being overridden by nonsense.

        The top-up is read from the question rather than from the keyword
        fallback: the fallback's arguments were filtered for the tool *it*
        chose, so a period would go missing whenever the two disagree.
        """
        allowed = ALLOWED_ARGS.get(tool, set())
        args = {k: v for k, v in raw.items() if k in allowed and v not in (None, "")}
        if args.get("key") and not valid_period_key(str(args["key"]).strip()):
            args.pop("key")
        for name, value in extract_args(question).items():
            if name in allowed:
                args.setdefault(name, value)
        return args

    # -- narration --------------------------------------------------------

    def chat_smalltalk(self, question: str, lang: str,
                       labels: dict[str, str]) -> str | None:
        """A short conversational reply, with no tool result behind it."""
        if not self.status().available:
            return None
        messages = [
            {"role": "system", "content": prompts.system_prompt(lang, labels)},
            {"role": "user",
             "content": prompts.smalltalk_prompt(question, lang)},
        ]
        try:
            data = self._chat(messages, num_predict=200)
            return ((data.get("message") or {}).get("content") or "").strip() or None
        except Exception:                               # noqa: BLE001
            return None

    def narrate(self, question: str, lang: str, labels: dict[str, str],
                tool: str, result: dict[str, Any],
                retry_violations: list[str] | None = None) -> str | None:
        if not self.status().available:
            return None
        messages = [
            {"role": "system", "content": prompts.system_prompt(lang, labels)},
            {"role": "user",
             "content": prompts.narrate_prompt(question, lang, tool, result)},
        ]
        if retry_violations:
            messages.append({
                "role": "user",
                "content": prompts.strict_retry_prompt(retry_violations),
            })
        try:
            return self._narrate_whole(messages)
        except Exception:                               # noqa: BLE001
            return None

    def _narrate_whole(self, messages: list[dict[str, Any]]) -> str | None:
        """The narrated answer, continued if the cap cut it off.

        A findings answer is several sections and tables long, and an endpoint
        that hits `max_tokens` returns what it had so far with no error — the
        reply simply stops mid-sentence. That reads as a wrong answer, so the
        stop reason is checked and the model is asked to carry on from where it
        stopped, up to `ai_continue_rounds` times.
        """
        budget = settings.ai_narrate_tokens
        data = self._chat(messages, num_predict=budget)
        message = data.get("message") or {}
        text = (message.get("content") or "").strip()

        for _ in range(max(0, settings.ai_continue_rounds)):
            if str(message.get("finish_reason") or "").lower() != "length":
                break
            if not text:
                # Nothing came back to continue from; a further round would
                # only repeat the same empty result.
                break
            follow = messages + [
                {"role": "assistant", "content": text},
                {"role": "user", "content": prompts.CONTINUE},
            ]
            data = self._chat(follow, num_predict=budget)
            message = data.get("message") or {}
            # Only the trailing side is trimmed: a continuation that resumes
            # mid-sentence carries the space that belongs before its first word.
            piece = (message.get("content") or "").rstrip()
            if not piece.strip():
                break
            text = _join_continuation(text, piece)

        return text or None


# The name the rest of the codebase imports. `OllamaClient` stays as an alias
# because that is what earlier notes and scripts refer to.
OllamaClient = AIClient

client = AIClient()
