"""Unit tests for infra/dagster_utils.py — terminate_dagster_run."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

RUN_ID = "e2248a82-19e4-4266-a25d-0192a3b8bf9a"


def _mock_settings(queue_worker_enabled: bool = False):
    cfg = MagicMock()
    cfg.queue_worker.enabled = queue_worker_enabled
    cfg.dagster.endpoint = "http://dagster:3000"
    return cfg


def _graphql_response(typename: str, extra: dict | None = None) -> MagicMock:
    payload = {"__typename": typename, **(extra or {})}
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"data": {"terminateRun": payload}}
    return resp


class TestTerminateDagsterRun:
    def test_success(self):
        from rag_api.infra.dagster_utils import terminate_dagster_run

        with (
            patch("rag_api.config.settings.get_settings", return_value=_mock_settings()),
            patch("httpx.post", return_value=_graphql_response("TerminateRunSuccess")),
        ):
            terminate_dagster_run(RUN_ID)  # no exception

    def test_run_not_found_is_noop(self):
        from rag_api.infra.dagster_utils import terminate_dagster_run

        with (
            patch("rag_api.config.settings.get_settings", return_value=_mock_settings()),
            patch("httpx.post", return_value=_graphql_response("RunNotFoundError")),
        ):
            terminate_dagster_run(RUN_ID)  # no exception

    def test_already_in_terminal_state_is_noop(self):
        """TerminateRunFailure with 'having status' means run is already done."""
        from rag_api.infra.dagster_utils import terminate_dagster_run

        msg = f"Run {RUN_ID} could not be terminated due to having status CANCELED."
        with (
            patch("rag_api.config.settings.get_settings", return_value=_mock_settings()),
            patch("httpx.post", return_value=_graphql_response("TerminateRunFailure", {"message": msg})),
        ):
            terminate_dagster_run(RUN_ID)  # no exception

    def test_unexpected_failure_raises(self):
        from rag_api.infra.dagster_utils import terminate_dagster_run

        msg = "Internal server error"
        with (
            patch("rag_api.config.settings.get_settings", return_value=_mock_settings()),
            patch("httpx.post", return_value=_graphql_response("TerminateRunFailure", {"message": msg})),
        ):
            with pytest.raises(RuntimeError, match="Dagster force-terminate failed"):
                terminate_dagster_run(RUN_ID)

    def test_queue_worker_mode_skips_http_call(self):
        from rag_api.infra.dagster_utils import terminate_dagster_run

        with (
            patch("rag_api.config.settings.get_settings", return_value=_mock_settings(queue_worker_enabled=True)),
            patch("httpx.post") as mock_post,
        ):
            terminate_dagster_run(RUN_ID)
            mock_post.assert_not_called()


def _runs_response(runs: list[dict]) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "data": {"runsOrError": {"__typename": "Runs", "results": runs}}
    }
    return resp


class TestFindActiveRunIdsByDocIds:
    def test_empty_doc_ids_skips_http_call(self):
        from rag_api.infra.dagster_utils import find_active_run_ids_by_doc_ids

        with patch("httpx.post") as mock_post:
            assert find_active_run_ids_by_doc_ids([]) == []
            mock_post.assert_not_called()

    def test_matches_tagged_runs(self):
        from rag_api.infra.dagster_utils import find_active_run_ids_by_doc_ids

        runs = [
            {"runId": "run-1", "tags": [{"key": "doc_id", "value": "doc-a"}]},
            {"runId": "run-2", "tags": [{"key": "doc_id", "value": "doc-b"}]},
            {"runId": "run-3", "tags": [{"key": "doc_id", "value": "doc-unrelated"}]},
        ]
        with (
            patch("rag_api.config.settings.get_settings", return_value=_mock_settings()),
            patch("httpx.post", return_value=_runs_response(runs)),
        ):
            result = find_active_run_ids_by_doc_ids(["doc-a", "doc-b"])
        assert set(result) == {"run-1", "run-2"}

    def test_no_matching_runs_returns_empty(self):
        from rag_api.infra.dagster_utils import find_active_run_ids_by_doc_ids

        runs = [{"runId": "run-1", "tags": [{"key": "doc_id", "value": "doc-unrelated"}]}]
        with (
            patch("rag_api.config.settings.get_settings", return_value=_mock_settings()),
            patch("httpx.post", return_value=_runs_response(runs)),
        ):
            assert find_active_run_ids_by_doc_ids(["doc-a"]) == []

    def test_queue_worker_mode_skips_http_call(self):
        from rag_api.infra.dagster_utils import find_active_run_ids_by_doc_ids

        with (
            patch("rag_api.config.settings.get_settings", return_value=_mock_settings(queue_worker_enabled=True)),
            patch("httpx.post") as mock_post,
        ):
            assert find_active_run_ids_by_doc_ids(["doc-a"]) == []
            mock_post.assert_not_called()

    def test_graphql_error_returns_empty(self):
        from rag_api.infra.dagster_utils import find_active_run_ids_by_doc_ids

        with (
            patch("rag_api.config.settings.get_settings", return_value=_mock_settings()),
            patch("httpx.post", side_effect=OSError("connection refused")),
        ):
            assert find_active_run_ids_by_doc_ids(["doc-a"]) == []
