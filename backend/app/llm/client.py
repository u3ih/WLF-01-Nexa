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
from . import prompts, smalltalk
from .tools import ALLOWED_ARGS, TOOLS

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
PERIOD_KEY = re.compile(r"(20\d{2})[-/](0?[1-9]|1[0-2])|(20\d{2})-?Q([1-4])|(20\d{2})",
                        re.I)
REF_IN_TEXT = re.compile(r"\b((?:ACC|CRD)-\d{3,5})\b", re.I)

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
    if re.search(r"quý|quarter", lowered):
        args["period"] = "quarter"
    elif re.search(r"năm nay|cả năm|this year|year", lowered):
        args["period"] = "year"
    else:
        args["period"] = "month"
    period = PERIOD_KEY.search(question)
    if period and period.group(1) and period.group(2):
        args["key"] = f"{period.group(1)}-{int(period.group(2)):02d}"
    elif period and period.group(3) and period.group(4):
        args["key"] = f"{period.group(3)}-Q{period.group(4)}"
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
            return _request("POST", "/api/chat", payload)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 400:
                raise
            if tools:
                raise ToolsUnsupported(_error_text(exc)) from exc
            # Older Ollama builds, or non-thinking models, reject "think".
            payload.pop("think", None)
            return _request("POST", "/api/chat", payload)


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
                            "tool_calls": calls}}


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
        """Keyword-first, model-second.

        The keyword table is exact for the phrasings this dataset is built
        around, and it costs nothing. The model is asked only when the keywords
        are inconclusive, which also keeps a turn down to a single model call.
        """
        status = self.status()
        fallback = keyword_route(question)
        if fallback.name != DEFAULT_TOOL:
            return fallback
        if not status.available:
            # No model to read the meaning, so the phrase list is all we have.
            # It is deliberately narrow: it only fires on a bare opener.
            if smalltalk.classify(question):
                return ToolCall(CHAT_ONLY, {}, "keyword")
            return fallback

        messages = [
            {"role": "system", "content": prompts.system_prompt(lang, labels)},
            {"role": "user", "content": prompts.router_prompt(question)},
        ]
        try:
            if status.mode == "native_tools":
                data = self._chat(
                    [
                        {"role": "system",
                         "content": prompts.system_prompt(lang, labels)
                         + "\n\n" + prompts.TOOL_CHOICE},
                        {"role": "user", "content": question},
                    ],
                    tools=prompts.native_tool_schemas(),
                    num_predict=300,
                )
                calls = (data.get("message") or {}).get("tool_calls") or []
                if not calls:
                    # The keyword table already had no opinion, and the model —
                    # holding the full tool list — chose not to use any of them.
                    # Two independent "not a data question" signals is enough.
                    return ToolCall(CHAT_ONLY, {}, "native_tools")
                if calls:
                    function = calls[0].get("function", {})
                    name = function.get("name", "")
                    raw_args = function.get("arguments") or {}
                    if isinstance(raw_args, str):
                        raw_args = json.loads(raw_args or "{}")
                    if name in TOOLS:
                        allowed = ALLOWED_ARGS.get(name, set())
                        args = {k: v for k, v in raw_args.items() if k in allowed}
                        return ToolCall(name, args, "native_tools")
                return fallback

            data = self._chat(messages, num_predict=200)
            content = (data.get("message") or {}).get("content", "")
            block = JSON_BLOCK.search(content or "")
            if block:
                parsed = json.loads(block.group(0))
                name = parsed.get("tool", "")
                if name == CHAT_ONLY:
                    return ToolCall(CHAT_ONLY, {}, "json_router")
                if name in TOOLS:
                    allowed = ALLOWED_ARGS.get(name, set())
                    raw_args = parsed.get("args") or {}
                    args = {k: v for k, v in raw_args.items() if k in allowed}
                    # keep any period/amount the question itself states
                    for key, value in fallback.args.items():
                        args.setdefault(key, value)
                    return ToolCall(name, args, "json_router")
        except Exception:                               # noqa: BLE001
            return fallback
        return fallback

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
                "content": prompts.STRICT_RETRY.format(
                    violations=", ".join(retry_violations)),
            })
        try:
            data = self._chat(messages, num_predict=900)
            return ((data.get("message") or {}).get("content") or "").strip() or None
        except Exception:                               # noqa: BLE001
            return None


# The name the rest of the codebase imports. `OllamaClient` stays as an alias
# because that is what earlier notes and scripts refer to.
OllamaClient = AIClient

client = AIClient()
