"""Settings.from_yaml env var override tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

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


# ──────────────────────────────────────────────
# resolve_settings(kb_id) — docs/internal/design/kb-settings-override.md
# ──────────────────────────────────────────────

@pytest.fixture
def base_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Fixed Settings instance so resolve_settings() tests don't depend on the real
    process-wide singleton / settings.yaml."""
    settings = Settings()
    monkeypatch.setattr("rag_api.config.settings.get_settings", lambda: settings)
    return settings


def test_resolve_settings_none_kb_id_returns_global(base_settings: Settings) -> None:
    from rag_api.config.settings import resolve_settings

    assert resolve_settings(None) is base_settings


def test_resolve_settings_no_overrides_returns_global_instance(base_settings: Settings) -> None:
    from rag_api.config.settings import resolve_settings

    with patch("rag_api.infra.postgres.get_kb_settings_overrides", return_value={}):
        assert resolve_settings("kb-01") is base_settings


def test_resolve_settings_applies_flat_dot_key_overrides(base_settings: Settings) -> None:
    from rag_api.config.settings import resolve_settings

    overrides = {
        "ingestion.max_file_size_mb": 50,
        "chunking.chunk_size": 512,
        "dedup.enabled": False,
    }
    with patch("rag_api.infra.postgres.get_kb_settings_overrides", return_value=overrides):
        resolved = resolve_settings("kb-01")

    assert resolved.ingestion.max_file_size_mb == 50
    assert resolved.chunking.chunk_size == 512
    assert resolved.dedup.enabled is False
    # untouched fields still fall back to the global value
    assert resolved.chunking.chunk_overlap == base_settings.chunking.chunk_overlap
    # the global instance itself is never mutated
    assert base_settings.ingestion.max_file_size_mb != 50


def test_resolve_settings_applies_nested_dot_key_override(base_settings: Settings) -> None:
    from rag_api.config.settings import resolve_settings

    overrides = {"dedup.simhash.hamming_identical_threshold": 7}
    with patch("rag_api.infra.postgres.get_kb_settings_overrides", return_value=overrides):
        resolved = resolve_settings("kb-01")

    assert resolved.dedup.simhash.hamming_identical_threshold == 7
    # sibling nested fields fall back to global
    assert resolved.dedup.simhash.hamming_similar_threshold == base_settings.dedup.simhash.hamming_similar_threshold


# ──────────────────────────────────────────────
# validate_override_key — allow-list + deny-list + field-path existence
# ──────────────────────────────────────────────

def test_validate_override_key_accepts_known_scalar_field() -> None:
    from rag_api.config.settings import validate_override_key

    validate_override_key(Settings, "ingestion.max_file_size_mb")
    validate_override_key(Settings, "chunking.chunk_size")
    validate_override_key(Settings, "dedup.enabled")


def test_validate_override_key_accepts_known_nested_field() -> None:
    from rag_api.config.settings import validate_override_key

    validate_override_key(Settings, "dedup.simhash.hamming_identical_threshold")


def test_validate_override_key_rejects_keys_outside_allowed_sections() -> None:
    """Deny-by-default outside ingestion/chunking/dedup — must not be satisfiable just by
    being absent from the deny-list (this is the security fix from the design review)."""
    from rag_api.config.settings import validate_override_key
    from rag_api.exceptions import IngestValidationError

    for key in ("provider.openai_api_key", "redis.password", "postgres.password", "s3.secret_key"):
        with pytest.raises(IngestValidationError, match="not overridable"):
            validate_override_key(Settings, key)


def test_validate_override_key_rejects_deny_listed_keys() -> None:
    from rag_api.config.settings import EXCLUDED_OVERRIDE_KEYS, validate_override_key
    from rag_api.exceptions import IngestValidationError

    for key in EXCLUDED_OVERRIDE_KEYS:
        with pytest.raises(IngestValidationError, match="not overridable"):
            validate_override_key(Settings, key)


def test_validate_override_key_rejects_unknown_field() -> None:
    from rag_api.config.settings import validate_override_key
    from rag_api.exceptions import IngestValidationError

    with pytest.raises(IngestValidationError, match="Unknown settings key"):
        validate_override_key(Settings, "ingestion.does_not_exist")


def test_validate_override_key_rejects_path_through_scalar_field() -> None:
    """A key that dots one level past an already-scalar field (e.g. dedup.enabled.foo) must
    be rejected here — letting it through crashes _apply_dotted_overrides with a TypeError on
    every subsequent resolve_settings() call for that KB."""
    from rag_api.config.settings import validate_override_key
    from rag_api.exceptions import IngestValidationError

    with pytest.raises(IngestValidationError, match="Unknown settings key"):
        validate_override_key(Settings, "dedup.enabled.foo")


# ──────────────────────────────────────────────
# _apply_dotted_overrides
# ──────────────────────────────────────────────

def test_apply_dotted_overrides_merges_into_nested_dict() -> None:
    from rag_api.config.settings import _apply_dotted_overrides

    base = {"ingestion": {"max_file_size_mb": 200}, "chunking": {"chunk_size": 1024}}
    merged = _apply_dotted_overrides(
        base, {"ingestion.max_file_size_mb": 50, "dedup.enabled": False}
    )

    assert merged["ingestion"]["max_file_size_mb"] == 50
    assert merged["chunking"]["chunk_size"] == 1024
    assert merged["dedup"]["enabled"] is False
