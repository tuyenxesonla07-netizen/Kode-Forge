# tests/workflow/test_event_store.py
"""Tests for tools/workflow/event_store.py — PipelineEventStore."""

import json
import tempfile
from pathlib import Path

import pytest

from tools.workflow.event_store import (
    EventType,
    PipelineEvent,
    PipelineEventStore,
)


class TestEventType:
    def test_all_values_are_strings(self):
        for et in EventType:
            assert isinstance(et.value, str)
            assert len(et.value) > 0


class TestPipelineEvent:
    def test_to_dict_round_trip(self):
        evt = PipelineEvent(
            event_id="abc",
            run_id="run-1",
            event_type=EventType.PIPELINE_STARTED,
            timestamp="2026-01-01T00:00:00+00:00",
            data={"requirement": "test"},
            seq=0,
        )
        d = evt.to_dict()
        restored = PipelineEvent.from_dict(d)
        assert restored.event_id == evt.event_id
        assert restored.run_id == evt.run_id
        assert restored.data == evt.data
        assert restored.seq == evt.seq


class TestPipelineEventStore:
    def test_append_increments_sequence(self):
        store = PipelineEventStore(run_id="test-1")
        e0 = store.append(EventType.PIPELINE_STARTED, {"requirement": "x"})
        e1 = store.append(EventType.PHASE_STARTED, {"phase": "compile"})
        assert e0.seq == 0
        assert e1.seq == 1
        assert len(store.events) == 2

    def test_project_status_transitions(self):
        store = PipelineEventStore(run_id="test-2")
        assert store.project()["status"] == "pending"

        store.append(EventType.PIPELINE_STARTED, {"requirement": "Build auth"})
        assert store.project()["status"] == "running"
        assert store.project()["requirement"] == "Build auth"

        store.append(EventType.PIPELINE_COMPLETED, {})
        assert store.project()["status"] == "success"

    def test_project_failed(self):
        store = PipelineEventStore(run_id="test-3")
        store.append(EventType.PIPELINE_STARTED, {})
        store.append(EventType.PIPELINE_FAILED, {"error": "timeout"})
        p = store.project()
        assert p["status"] == "failed"
        assert p["error"] == "timeout"

    def test_project_blocked(self):
        store = PipelineEventStore(run_id="test-4")
        store.append(EventType.PIPELINE_STARTED, {})
        store.append(EventType.PIPELINE_BLOCKED, {"reason": "injection detected"})
        p = store.project()
        assert p["status"] == "blocked"
        assert p["security_blocked"] is True
        assert "injection" in p["error"]

    def test_project_phases_completed(self):
        store = PipelineEventStore(run_id="test-5")
        store.append(EventType.PHASE_STARTED, {"phase": "compilation"})
        store.append(EventType.PHASE_COMPLETED, {"phase": "compilation"})
        store.append(EventType.PHASE_COMPLETED, {"phase": "code_generation"})
        p = store.project()
        assert "compilation" in p["phases_completed"]
        assert "code_generation" in p["phases_completed"]
        assert len(p["phases_failed"]) == 0

    def test_project_phases_failed(self):
        store = PipelineEventStore(run_id="test-6")
        store.append(EventType.PHASE_FAILED, {"phase": "quality_review"})
        p = store.project()
        assert "quality_review" in p["phases_failed"]

    def test_project_quality_scores(self):
        store = PipelineEventStore(run_id="test-7")
        store.append(EventType.QUALITY_GATE_FAILED, {"score": 0.55})
        store.append(EventType.QUALITY_FIX_DONE, {})
        store.append(EventType.QUALITY_GATE_PASSED, {"score": 0.82})
        p = store.project()
        assert p["quality_scores"] == [0.55, 0.82]
        assert p["quality_passed"] is True
        assert p["fix_iterations"] == 1

    def test_project_hitl(self):
        store = PipelineEventStore(run_id="test-8")
        store.append(EventType.HITL_APPROVAL_REQUESTED, {})
        assert store.project()["hitl_pending"] is True
        store.append(EventType.HITL_APPROVED, {})
        assert store.project()["hitl_pending"] is False

    def test_project_agents(self):
        store = PipelineEventStore(run_id="test-9")
        store.append(EventType.AGENT_COMPLETED, {"agent": "authentication"})
        store.append(EventType.AGENT_COMPLETED, {"agent": "api_integration"})
        p = store.project()
        assert "authentication" in p["agents_completed"]
        assert "api_integration" in p["agents_completed"]

    def test_project_event_count(self):
        store = PipelineEventStore(run_id="test-10")
        for et in [EventType.PIPELINE_STARTED, EventType.PHASE_COMPLETED, EventType.PIPELINE_COMPLETED]:
            store.append(et, {})
        assert store.project()["event_count"] == 3

    def test_persist_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = PipelineEventStore(run_id="persist-1", base_dir=tmp)
            store.append(EventType.PIPELINE_STARTED, {"requirement": "Build JWT auth"})
            store.append(EventType.PHASE_COMPLETED, {"phase": "compilation", "modules": 2})
            store.append(EventType.QUALITY_GATE_PASSED, {"score": 0.88})
            store.append(EventType.PIPELINE_COMPLETED, {})
            run_dir = store.persist()

            # events.jsonl exists and is valid JSONL
            events_path = run_dir / "events.jsonl"
            assert events_path.exists()
            lines = [json.loads(l) for l in events_path.read_text().splitlines()]
            assert len(lines) == 4
            assert lines[0]["event_type"] == EventType.PIPELINE_STARTED

            # execution_state.json is the read-only projection
            state_path = run_dir / "execution_state.json"
            assert state_path.exists()
            state = json.loads(state_path.read_text())
            assert state["status"] == "success"
            assert state["quality_scores"] == [0.88]

            # Load from disk and verify projection is identical
            restored = PipelineEventStore.load("persist-1", base_dir=tmp)
            assert len(restored.events) == 4
            rp = restored.project()
            assert rp["status"] == "success"
            assert rp["requirement"] == "Build JWT auth"
            assert "compilation" in rp["phases_completed"]
            assert rp["quality_passed"] is True

    def test_load_nonexistent_run_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = PipelineEventStore.load("nonexistent-run", base_dir=tmp)
            assert len(store.events) == 0
            assert store.project()["status"] == "pending"

    def test_list_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            for run_id in ["run-a", "run-b", "run-c"]:
                s = PipelineEventStore(run_id=run_id, base_dir=tmp)
                s.append(EventType.PIPELINE_STARTED, {})
                s.persist()
            runs = PipelineEventStore.list_runs(base_dir=tmp)
            assert set(runs) == {"run-a", "run-b", "run-c"}

    def test_list_runs_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            assert PipelineEventStore.list_runs(base_dir=tmp) == []

    def test_no_duplicate_phases(self):
        store = PipelineEventStore(run_id="dup-1")
        store.append(EventType.PHASE_COMPLETED, {"phase": "compile"})
        store.append(EventType.PHASE_COMPLETED, {"phase": "compile"})  # duplicate
        p = store.project()
        assert p["phases_completed"].count("compile") == 1

    def test_checkpoint_event(self):
        store = PipelineEventStore(run_id="chk-1")
        store.append(EventType.PIPELINE_STARTED, {})
        store.append(EventType.CHECKPOINT, {"label": "after_phase1", "modules": 2})
        assert len(store.events) == 2
        assert store.events[-1].event_type == EventType.CHECKPOINT

    def test_security_blocked_via_security_event(self):
        store = PipelineEventStore(run_id="sec-1")
        store.append(EventType.PIPELINE_STARTED, {})
        store.append(EventType.SECURITY_BLOCKED, {"reason": "PII detected"})
        p = store.project()
        assert p["security_blocked"] is True
        assert p["status"] == "blocked"
