"""Settings.from_yaml env var override tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from rag_api.config.settings import Settings

_YAML_BODY = """
s3:
  access_key: "yaml-access"
  secret_key: "yaml-secret"
redis:
  password: "yaml-redis-pw"
postgres:
  user: "yaml-postgres-user"
  password: "yaml-postgres-pw"
retrieval:
  rerank:
    api_key: "yaml-rerank-key"
tracing:
  langfuse_public_key: "yaml-langfuse-public"
  langfuse_secret_key: "yaml-langfuse-secret"
provider:
  openai_api_key: "yaml-openai-key"
"""


@pytest.fixture
def settings_yaml(tmp_path: Path) -> Path:
    path = tmp_path / "settings.yaml"
    path.write_text(_YAML_BODY)
    return path


def test_secret_fields_default_to_yaml_values(settings_yaml: Path) -> None:
    settings = Settings.from_yaml(settings_yaml)

    assert settings.s3.access_key == "yaml-access"
    assert settings.s3.secret_key == "yaml-secret"
    assert settings.redis.password == "yaml-redis-pw"
    assert settings.postgres.user == "yaml-postgres-user"
    assert settings.postgres.password == "yaml-postgres-pw"
    assert settings.retrieval.rerank.api_key == "yaml-rerank-key"
    assert settings.tracing.langfuse_public_key == "yaml-langfuse-public"
    assert settings.tracing.langfuse_secret_key == "yaml-langfuse-secret"
    assert settings.provider.openai_api_key == "yaml-openai-key"


def test_env_vars_override_yaml_secret_values(settings_yaml: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("S3_ACCESS_KEY", "env-access")
    monkeypatch.setenv("S3_SECRET_KEY", "env-secret")
    monkeypatch.setenv("REDIS_PASSWORD", "env-redis-pw")
    monkeypatch.setenv("POSTGRES_USER", "env-postgres-user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "env-postgres-pw")
    monkeypatch.setenv("RERANKER_API_KEY", "env-rerank-key")
    monkeypatch.setenv("TRACING_LANGFUSE_PUBLIC_KEY", "env-langfuse-public")
    monkeypatch.setenv("TRACING_LANGFUSE_SECRET_KEY", "env-langfuse-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "env-openai-key")

    settings = Settings.from_yaml(settings_yaml)

    assert settings.s3.access_key == "env-access"
    assert settings.s3.secret_key == "env-secret"
    assert settings.redis.password == "env-redis-pw"
    assert settings.postgres.user == "env-postgres-user"
    assert settings.postgres.password == "env-postgres-pw"
    assert settings.retrieval.rerank.api_key == "env-rerank-key"
    assert settings.tracing.langfuse_public_key == "env-langfuse-public"
    assert settings.tracing.langfuse_secret_key == "env-langfuse-secret"
    assert settings.provider.openai_api_key == "env-openai-key"


def test_rerank_env_override_applies_without_yaml_retrieval_section(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text("s3:\n  access_key: admin\n")
    monkeypatch.setenv("RERANKER_API_KEY", "env-rerank-key")

    settings = Settings.from_yaml(path)

    assert settings.retrieval.rerank.api_key == "env-rerank-key"
