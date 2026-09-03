"""Unit tests for rag_api.hooks — registry, emit ordering, exception propagation."""

from __future__ import annotations

import sys

import pytest

from rag_api.hooks import BeforeDocCreate, HookAbort, emit, register, unregister


@pytest.fixture(autouse=True)
def _isolate(reset_hooks):
    """Every test in this module runs against an empty registry."""
    return reset_hooks


class TestEmit:
    def test_runs_callbacks_in_registration_order(self):
        calls: list[str] = []
        register(BeforeDocCreate, lambda ev: calls.append("first"))
        register(BeforeDocCreate, lambda ev: calls.append("second"))

        emit(BeforeDocCreate(kb_id="kb-1"))

        assert calls == ["first", "second"]

    def test_passes_the_event_to_the_callback(self):
        seen: list[BeforeDocCreate] = []
        register(BeforeDocCreate, seen.append)

        ev = BeforeDocCreate(kb_id="kb-1", principal={"user": "u1"}, source_type="s3")
        emit(ev)

        assert seen == [ev]
        assert seen[0].principal == {"user": "u1"}

    def test_noop_when_no_callback_registered(self):
        # No registration for this event type -- must not raise.
        emit(BeforeDocCreate(kb_id="kb-1"))

    def test_only_callbacks_for_the_event_type_run(self):
        calls: list[str] = []

        class OtherEvent:
            pass

        register(BeforeDocCreate, lambda ev: calls.append("bdc"))
        register(OtherEvent, lambda ev: calls.append("other"))

        emit(BeforeDocCreate(kb_id="kb-1"))

        assert calls == ["bdc"]

    def test_callback_exception_propagates_and_stops_later_callbacks(self):
        calls: list[str] = []

        def boom(ev):
            calls.append("boom")
            raise RuntimeError("callback failed")

        register(BeforeDocCreate, boom)
        register(BeforeDocCreate, lambda ev: calls.append("never"))

        with pytest.raises(RuntimeError, match="callback failed"):
            emit(BeforeDocCreate(kb_id="kb-1"))

        assert calls == ["boom"]

    def test_hookabort_propagates_unchanged(self):
        class QuotaError(HookAbort):
            pass

        def deny(ev):
            raise QuotaError("limit reached")

        register(BeforeDocCreate, deny)

        with pytest.raises(HookAbort, match="limit reached"):
            emit(BeforeDocCreate(kb_id="kb-1"))


class TestRegistration:
    def test_unregister_removes_callback(self):
        calls: list[str] = []

        def cb(ev):
            calls.append("cb")

        register(BeforeDocCreate, cb)
        unregister(BeforeDocCreate, cb)
        emit(BeforeDocCreate(kb_id="kb-1"))

        assert calls == []

    def test_unregister_unknown_callback_is_noop(self):
        unregister(BeforeDocCreate, lambda ev: None)  # never registered -- must not raise

    def test_duplicate_registration_runs_once(self):
        calls: list[str] = []

        def cb(ev):
            calls.append("cb")

        register(BeforeDocCreate, cb)
        register(BeforeDocCreate, cb)
        emit(BeforeDocCreate(kb_id="kb-1"))

        assert calls == ["cb"]


class TestModuleContract:
    def test_hookabort_is_the_same_class_as_in_exceptions(self):
        from rag_api.exceptions import HookAbort as ExcHookAbort

        assert HookAbort is ExcHookAbort

    def test_hookabort_is_not_a_ragerror(self):
        from rag_api.exceptions import RAGError

        assert not issubclass(HookAbort, RAGError)

    def test_before_doc_create_is_frozen(self):
        ev = BeforeDocCreate(kb_id="kb-1")
        with pytest.raises(Exception):
            ev.kb_id = "kb-2"  # type: ignore[misc]

    def test_importing_hooks_does_not_pull_in_connectors_or_api(self):
        # Run in a clean interpreter: mutating sys.modules / reloading in-process
        # would corrupt the shared hooks registry for other tests.
        import subprocess

        code = (
            "import sys; import rag_api.hooks; "
            "bad = [m for m in sys.modules if m.startswith(('rag_api.connectors', 'rag_api.api'))]; "
            "print(bad); sys.exit(1 if bad else 0)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, f"hooks import pulled in: {result.stdout.strip()}"
