"""Which model endpoint the assistant talks to comes from `.env` alone.

These tests pin that contract without touching the network: the transport is
chosen from the configured URL / key, an OpenAI-compatible reply is reshaped
into the one form the router and the narrator read, and an endpoint that
refuses the tool schema drops the tier instead of looking like "no tool needed".
"""

from __future__ import annotations

import httpx
import pytest

from app.config import settings
from app.llm import client as client_module
from app.llm.client import (AIClient, OllamaBackend, OpenAIBackend,
                            ToolsUnsupported)


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch):
    """Every test sets its own endpoint, and none of them leaks into the next."""
    monkeypatch.setattr(settings, "offline_mode", False)
    monkeypatch.setattr(settings, "ai_retries", 0)
    monkeypatch.setattr(settings, "ai_native_tools", "auto")
    monkeypatch.setattr(settings, "ai_api_key", "")
    yield


def _set_endpoint(monkeypatch, url: str, provider: str = "auto",
                  key: str = "", model: str = "test-model") -> None:
    monkeypatch.setattr(settings, "ai_url", url)
    monkeypatch.setattr(settings, "ai_provider", provider)
    monkeypatch.setattr(settings, "ai_api_key", key)
    monkeypatch.setattr(settings, "ai_model", model)


# --------------------------------------------------------- provider selection

@pytest.mark.parametrize("url, key, expected", [
    ("http://localhost:11434", "", "ollama"),
    ("http://host.docker.internal:11434", "", "ollama"),
    ("https://ark.ap-southeast.bytepluses.com/api/v3", "", "openai"),
    ("https://api.openai.com/v1", "", "openai"),
    # A bare host plus a key is a gateway that simply does not advertise itself.
    ("https://models.internal.example", "secret", "openai"),
])
def test_auto_picks_the_transport_from_the_url_and_key(monkeypatch, url, key,
                                                       expected):
    _set_endpoint(monkeypatch, url, "auto", key)
    assert AIClient._candidates()[0].name == expected


@pytest.mark.parametrize("provider, expected", [
    ("ollama", ["ollama"]),
    ("openai", ["openai"]),
    ("OpenAI", ["openai"]),
])
def test_an_explicit_provider_is_not_second_guessed(monkeypatch, provider,
                                                    expected):
    # The URL argues for the other transport; the setting still wins, and no
    # fallback candidate is offered.
    _set_endpoint(monkeypatch, "http://localhost:11434", provider)
    assert [b.name for b in AIClient._candidates()] == expected


def test_auto_falls_back_to_the_other_transport(monkeypatch):
    """A versioned URL is tried as OpenAI first, but Ollama still gets a turn."""
    _set_endpoint(monkeypatch, "https://gateway.example/v1", "auto")
    assert [b.name for b in AIClient._candidates()] == ["openai", "ollama"]


# --------------------------------------------------------------- reply shaping

def test_an_openai_reply_is_reshaped_into_the_form_the_router_reads():
    reshaped = OpenAIBackend._normalise({
        "choices": [{"message": {
            "content": "hi",
            "tool_calls": [{"function": {"name": "get_report",
                                         "arguments": '{"period":"month"}'}}],
        }}],
    })
    message = reshaped["message"]
    assert message["content"] == "hi"
    assert message["tool_calls"][0]["function"]["name"] == "get_report"
    assert message["tool_calls"][0]["function"]["arguments"] == '{"period":"month"}'


def test_a_reply_with_no_choices_does_not_raise():
    assert OpenAIBackend._normalise({}) == {"message": {"content": "",
                                                        "tool_calls": []}}


def test_the_openai_request_carries_the_key_and_a_deterministic_temperature(
        monkeypatch):
    _set_endpoint(monkeypatch, "https://gateway.example/v1", "openai",
                  key="secret-key")
    seen: dict = {}

    def fake_request(method, path, payload=None, headers=None, timeout=None):
        seen.update({"method": method, "path": path, "payload": payload,
                     "headers": headers})
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(client_module, "_request", fake_request)
    result = OpenAIBackend().chat("m", [{"role": "user", "content": "q"}],
                                  None, 120)

    assert seen["path"] == "/chat/completions"
    assert seen["payload"]["temperature"] == 0
    assert seen["payload"]["max_tokens"] == 120
    assert seen["headers"]["authorization"] == "Bearer secret-key"
    assert result["message"]["content"] == "ok"


def test_an_endpoint_that_renamed_the_output_cap_is_retried(monkeypatch):
    _set_endpoint(monkeypatch, "https://gateway.example/v1", "openai")
    calls: list[dict] = []

    def fake_request(method, path, payload=None, headers=None, timeout=None):
        calls.append(payload)
        if "max_tokens" in payload:
            raise httpx.HTTPStatusError(
                "bad request",
                request=httpx.Request("POST", "https://gateway.example/v1"),
                response=httpx.Response(
                    400, text="use max_completion_tokens instead"),
            )
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(client_module, "_request", fake_request)
    result = OpenAIBackend().chat("m", [], None, 55)

    assert len(calls) == 2
    assert calls[1]["max_completion_tokens"] == 55
    assert result["message"]["content"] == "ok"


# ------------------------------------------------------------- tier behaviour

def test_a_rejected_tool_schema_drops_the_tier_instead_of_faking_small_talk(
        monkeypatch):
    _set_endpoint(monkeypatch, "https://gateway.example/v1", "openai")
    client = AIClient()
    monkeypatch.setattr(OpenAIBackend, "list_models",
                        lambda self: ["test-model"])
    assert client.status(refresh=True).mode == "native_tools"

    def refuse(self, model, messages, tools, num_predict):
        if tools:
            raise ToolsUnsupported("tools are not supported by this model")
        return {"message": {"content": "{}", "tool_calls": []}}

    monkeypatch.setattr(OpenAIBackend, "chat", refuse)

    with pytest.raises(ToolsUnsupported):
        client._chat([], tools=[{"type": "function"}], num_predict=10)

    # The next turn must not try tools again, and the model is still up.
    status = client.status()
    assert status.mode == "json_router"
    assert status.available is True


def test_native_tools_can_be_forced_off_by_configuration(monkeypatch):
    _set_endpoint(monkeypatch, "https://gateway.example/v1", "openai")
    monkeypatch.setattr(settings, "ai_native_tools", "false")
    monkeypatch.setattr(OpenAIBackend, "list_models",
                        lambda self: ["test-model"])
    assert AIClient().status(refresh=True).mode == "json_router"


def test_a_model_missing_from_a_gateway_listing_is_still_used(monkeypatch):
    """A hosted gateway serves deployment names it does not enumerate, so an
    absent name is a warning — not an outage."""
    _set_endpoint(monkeypatch, "https://gateway.example/v1", "openai")
    monkeypatch.setattr(OpenAIBackend, "list_models",
                        lambda self: ["something-else"])
    status = AIClient().status(refresh=True)
    assert status.available is True
    assert status.model == "test-model"
    assert "not in the endpoint's listing" in status.detail


def test_a_model_missing_from_ollama_falls_back_to_an_installed_one(monkeypatch):
    _set_endpoint(monkeypatch, "http://localhost:11434", "ollama")
    monkeypatch.setattr(OllamaBackend, "list_models",
                        lambda self: ["qwen3:8b", "nomic-embed-text"])
    monkeypatch.setattr(OllamaBackend, "supports_tools", lambda self, m: False)
    status = AIClient().status(refresh=True)
    assert status.available is True
    assert status.model == "qwen3:8b"


# ------------------------------------------------------------- outage reports

def test_a_rejected_key_is_reported_as_a_key_problem(monkeypatch):
    _set_endpoint(monkeypatch, "https://gateway.example/v1", "openai")

    def unauthorised(self):
        raise httpx.HTTPStatusError(
            "unauthorised",
            request=httpx.Request("GET", "https://gateway.example/v1/models"),
            response=httpx.Response(401),
        )

    monkeypatch.setattr(OpenAIBackend, "list_models", unauthorised)
    status = AIClient().status(refresh=True)
    assert status.available is False
    assert status.mode == "offline"
    assert "NEXA_AI_API_KEY" in status.detail


def test_offline_mode_skips_the_probe_entirely(monkeypatch):
    _set_endpoint(monkeypatch, "https://gateway.example/v1", "openai")
    monkeypatch.setattr(settings, "offline_mode", True)

    def explode(self):                                  # pragma: no cover
        raise AssertionError("no probe may run in offline mode")

    monkeypatch.setattr(OpenAIBackend, "list_models", explode)
    status = AIClient().status(refresh=True)
    assert status.available is False
    assert status.mode == "offline"


def test_no_api_key_ever_appears_in_the_reported_status(monkeypatch):
    _set_endpoint(monkeypatch, "https://gateway.example/v1", "openai",
                  key="super-secret-key")
    monkeypatch.setattr(OpenAIBackend, "list_models",
                        lambda self: ["test-model"])
    status = AIClient().status(refresh=True)
    assert "super-secret-key" not in str(status.as_dict())
