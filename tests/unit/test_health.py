"""Unit tests for GET /ready — provider generalization branch (US-50)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from rag_api.api.app import create_app
from rag_api.config.settings import ProviderSettings


@pytest.fixture
def client():
    with patch("rag_api.api.app._init_infrastructure"):
        app = create_app()
    return TestClient(app)


def _patch_infra_ok(stack):
    """All infra pings green; returns the ExitStack-entered patches."""
    stack.enter_context(patch("rag_api.infra.qdrant.ping", return_value=True))
    stack.enter_context(patch("rag_api.infra.redis.ping", return_value=True))
    stack.enter_context(patch("rag_api.infra.postgres.ping", return_value=True))
    stack.enter_context(
        patch("rag_api.api.routers.health._s3_ok", new=_async_true)
    )


async def _async_true() -> bool:
    return True


def _settings_with_provider(**kwargs):
    return SimpleNamespace(provider=ProviderSettings(**kwargs))


class _RecordingProviderOk:
    """Stand-in for health._provider_ok that records (label, v1_base, api_key) and returns True."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []

    async def __call__(self, label: str, v1_base: str, api_key: str | None) -> bool:
        self.calls.append((label, v1_base, api_key))
        return True


def _run_ready(client, stack, **provider_kwargs) -> tuple[dict, _RecordingProviderOk]:
    rec = _RecordingProviderOk()
    _patch_infra_ok(stack)
    stack.enter_context(
        patch(
            "rag_api.config.settings.get_settings",
            return_value=_settings_with_provider(**provider_kwargs),
        )
    )
    stack.enter_context(patch("rag_api.api.routers.health._provider_ok", new=rec))
    return client.get("/ready").json(), rec


def test_ready_probes_ollama_at_compat_v1_models(client):
    from contextlib import ExitStack

    with ExitStack() as stack:
        body, rec = _run_ready(client, stack, name="ollama")

    assert body["provider"] == "ollama"
    assert body["checks"]["ollama"] is True
    # bare-host provider.url -> /v1 compat layer appended, no api_key for ollama
    assert rec.calls == [("ollama", "http://ollama:11434/v1", None)]


def test_ready_probes_openai_at_saas_base(client):
    from contextlib import ExitStack

    with ExitStack() as stack:
        body, rec = _run_ready(client, stack, name="openai", api_key="sk-x")

    assert body["provider"] == "openai"
    assert body["checks"]["openai"] is True
    assert rec.calls == [("openai", "https://api.openai.com/v1", "sk-x")]


def test_ready_probes_jina_at_saas_base(client):
    from contextlib import ExitStack

    with ExitStack() as stack:
        body, rec = _run_ready(client, stack, name="jina", api_key="jina-x")

    assert body["provider"] == "jina"
    assert body["checks"]["jina"] is True
    assert rec.calls == [("jina", "https://api.jina.ai/v1", "jina-x")]


def test_ready_probes_openai_compatible_provider_via_url(client):
    """An unknown (OpenAI-compatible) name with a base URL is probed at {url}/models and keyed
    by its own name so rag-admin can label the tile."""
    from contextlib import ExitStack

    with ExitStack() as stack:
        body, rec = _run_ready(client, stack, name="vllm", url="http://vllm:8000/v1")

    assert body["provider"] == "vllm"
    assert body["checks"]["vllm"] is True
    assert rec.calls == [("vllm", "http://vllm:8000/v1", None)]


def test_ready_skips_probe_for_unknown_provider_without_url(client):
    """An unknown name with no url is a misconfiguration -- not probed, but still identified
    by the 'provider' field. Missing key must not be treated as a failure."""
    from contextlib import ExitStack

    with ExitStack() as stack:
        _patch_infra_ok(stack)
        stack.enter_context(
            patch(
                "rag_api.config.settings.get_settings",
                return_value=_settings_with_provider(name="vllm"),
            )
        )
        resp = client.get("/ready")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["provider"] == "vllm"
    assert "vllm" not in body["checks"]
