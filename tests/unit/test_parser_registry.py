"""parser_registry unit tests — register/unregister/post-processor API, default loading,
settings-driven plugin loading."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from llama_index.core import Document
from llama_index.core.readers.base import BaseReader

from rag_api.exceptions import ConfigError
from rag_api.pipeline.steps.parser import registry as parser_registry


@pytest.fixture(autouse=True)
def _reset_registry():
    """settings.yaml ships parser_plugins: [] by default, so _load_plugins() is a no-op
    unless a test patches get_settings() — no mocking needed for the default-registration
    tests below."""
    parser_registry.reset_registry()
    yield
    parser_registry.reset_registry()


class _FakeReader(BaseReader):
    def load_data(self, file: Path, extra_info: dict | None = None) -> list[Document]:
        return [Document(text="fake")]


class TestDefaults:
    def test_register_defaults_covers_all_document_extensions(self):
        parsers = parser_registry.get_parsers()

        for ext in (
            ".pdf", ".md", ".docx", ".doc", ".txt", ".hwp", ".html", ".htm", ".rst", ".eml",
            ".csv", ".tsv", ".json", ".epub", ".xlsx", ".xls", ".pptx", ".ppt",
        ):
            assert ext in parsers

    def test_register_defaults_covers_config_data_extensions(self):
        parsers = parser_registry.get_parsers()

        for ext in (".yaml", ".yml", ".properties"):
            assert ext in parsers

    def test_register_defaults_covers_code_extensions(self):
        from rag_api.pipeline.steps.parser.extensions import CODE_EXTENSIONS

        parsers = parser_registry.get_parsers()

        for ext in CODE_EXTENSIONS:
            assert ext in parsers

    def test_ensure_loaded_runs_defaults_and_plugins_exactly_once(self):
        with (
            patch.object(parser_registry, "_register_defaults") as mock_defaults,
            patch.object(parser_registry, "_load_plugins") as mock_plugins,
        ):
            parser_registry.get_parsers()
            parser_registry.get_parsers()
            parser_registry.supported_extensions()

        mock_defaults.assert_called_once()
        mock_plugins.assert_called_once()


class TestRegisterUnregister:
    def test_register_new_extension_is_added(self):
        parser_registry.register_parser(".xyz", _FakeReader())

        assert ".xyz" in parser_registry.supported_extensions()

    def test_register_existing_extension_replaces_reader(self):
        parser_registry.get_parsers()  # trigger default load first
        replacement = _FakeReader()
        parser_registry.register_parser(".pdf", replacement)

        assert parser_registry.get_parsers()[".pdf"] is replacement

    def test_unregister_removes_extension(self):
        parser_registry.get_parsers()  # trigger default load first
        parser_registry.unregister_parser(".hwp")

        assert ".hwp" not in parser_registry.supported_extensions()

    def test_unregister_unknown_extension_is_noop(self):
        parser_registry.unregister_parser(".doesnotexist")  # should not raise


class TestPostProcessors:
    def test_registered_post_processor_is_returned(self):
        def fn(documents, file_path, suffix):
            return []

        parser_registry.register_post_processor(fn)

        assert fn in parser_registry.get_post_processors()

    def test_no_post_processors_by_default(self):
        assert parser_registry.get_post_processors() == []


class TestPluginLoading:
    def test_plugin_register_function_is_invoked(self):
        with patch("rag_api.config.settings.get_settings") as mock_get_settings:
            mock_get_settings.return_value.ingestion.parser_plugins = [
                "tests.unit.fixtures.fake_parser_plugin:register"
            ]
            parsers = parser_registry.get_parsers()

        assert ".fake" in parsers

    def test_plugin_runs_after_defaults_and_can_replace_them(self):
        from tests.unit.fixtures.fake_parser_plugin import FakePdfReader

        with patch("rag_api.config.settings.get_settings") as mock_get_settings:
            mock_get_settings.return_value.ingestion.parser_plugins = [
                "tests.unit.fixtures.fake_parser_plugin:register"
            ]
            parsers = parser_registry.get_parsers()

        assert isinstance(parsers[".pdf"], FakePdfReader)

    def test_invalid_plugin_entry_raises_config_error(self):
        with patch("rag_api.config.settings.get_settings") as mock_get_settings:
            mock_get_settings.return_value.ingestion.parser_plugins = ["not-a-valid-entry"]

            with pytest.raises(ConfigError):
                parser_registry.get_parsers()

    def test_missing_module_raises_config_error(self):
        with patch("rag_api.config.settings.get_settings") as mock_get_settings:
            mock_get_settings.return_value.ingestion.parser_plugins = [
                "rag_api.does_not_exist:register"
            ]

            with pytest.raises(ConfigError):
                parser_registry.get_parsers()

    def test_missing_function_raises_config_error(self):
        with patch("rag_api.config.settings.get_settings") as mock_get_settings:
            mock_get_settings.return_value.ingestion.parser_plugins = [
                "tests.unit.fixtures.fake_parser_plugin:no_such_func"
            ]

            with pytest.raises(ConfigError):
                parser_registry.get_parsers()
