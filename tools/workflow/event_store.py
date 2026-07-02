# tools/workflow/event_store.py
"""
事件溯源状态管理 — PipelineEventStore

设计原则（借鉴 boss-skill 的 events.jsonl + execution.json 模式）：
  - events.jsonl  → append-only，每次 pipeline 执行追加，不可修改
  - execution_state.json → 只读投影，由事件流物化，不能直接写入

用法：
    store = PipelineEventStore(run_id="run-abc123")
    store.append(EventType.PIPELINE_STARTED, {"requirement": "Build JWT auth"})
    store.append(EventType.PHASE_COMPLETED, {"phase": "compilation", "modules": 2})

    projection = store.project()   # 当前状态的只读视图
    store.persist()                # 刷新到 .kodeforge/{run_id}/events.jsonl
    store.load(run_id)             # 从磁盘恢复，重建投影
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class EventType(str, Enum):
    PIPELINE_STARTED    = "pipeline.started"
    PIPELINE_COMPLETED  = "pipeline.completed"
    PIPELINE_FAILED     = "pipeline.failed"
    PIPELINE_BLOCKED    = "pipeline.blocked"

    PHASE_STARTED       = "phase.started"
    PHASE_COMPLETED     = "phase.completed"
    PHASE_FAILED        = "phase.failed"

    AGENT_STARTED       = "agent.started"
    AGENT_COMPLETED     = "agent.completed"
    AGENT_FAILED        = "agent.failed"

    QUALITY_GATE_PASSED = "quality.gate_passed"
    QUALITY_GATE_FAILED = "quality.gate_failed"
    QUALITY_FIX_STARTED = "quality.fix_started"
    QUALITY_FIX_DONE    = "quality.fix_done"

    HITL_APPROVAL_REQUESTED = "hitl.approval_requested"
    HITL_APPROVED           = "hitl.approved"
    HITL_REJECTED           = "hitl.rejected"

    SECURITY_BLOCKED    = "security.blocked"
    SECURITY_PASSED     = "security.passed"

    SEARCH_CONTEXT_RETRIEVED = "search.context_retrieved"
    FIX_CONTEXT_INJECTED     = "fix.context_injected"

    CHECKPOINT          = "checkpoint"


@dataclass
class PipelineEvent:
    event_id:   str
    run_id:     str
    event_type: str
    timestamp:  str
    data:       Dict[str, Any] = field(default_factory=dict)
    seq:        int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "event_id":   self.event_id,
            "run_id":     self.run_id,
            "event_type": self.event_type,
            "timestamp":  self.timestamp,
            "seq":        self.seq,
            "data":       self.data,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PipelineEvent":
        """Create instance from dictionary."""
        return cls(
            event_id=d["event_id"],
            run_id=d["run_id"],
            event_type=d["event_type"],
            timestamp=d["timestamp"],
            seq=d.get("seq", 0),
            data=d.get("data", {}),
        )


@dataclass
class PipelineProjection:
    """events.jsonl 的只读物化视图。直接写该对象无效——通过 append() 改变状态。"""
    run_id:            str
    status:            str = "pending"     # pending | running | success | failed | blocked
    started_at:        Optional[str] = None
    completed_at:      Optional[str] = None
    requirement:       str = ""
    phases_completed:  List[str] = field(default_factory=list)
    phases_failed:     List[str] = field(default_factory=list)
    agents_completed:  List[str] = field(default_factory=list)
    quality_scores:    List[float] = field(default_factory=list)
    quality_passed:    bool = False
    fix_iterations:    int = 0
    hitl_pending:      bool = False
    security_blocked:  bool = False
    error:             Optional[str] = None
    event_count:       int = 0
    last_event_type:   str = ""


class PipelineEventStore:
    """
    Append-only event log for a single pipeline run.

    Storage layout (when persisted):
        .kodeforge/<run_id>/events.jsonl        ← append-only
        .kodeforge/<run_id>/execution_state.json ← read-only projection (re-generated on load)
    """

    BASE_DIR = ".kodeforge"

    def __init__(
        self,
        run_id: Optional[str] = None,
        base_dir: str = BASE_DIR,
    ) -> None:
        self.run_id = run_id or f"run-{uuid.uuid4().hex[:8]}"
        self.base_dir = Path(base_dir)
        self.events: List[PipelineEvent] = []
        self._projection = PipelineProjection(run_id=self.run_id)

    # ── 写入 ─────────────────────────────────────────────────────────────────

    def append(self, event_type: EventType | str, data: Dict[str, Any] | None = None) -> PipelineEvent:
        """追加一条事件，立即更新内存投影。"""
        evt = PipelineEvent(
            event_id=uuid.uuid4().hex,
            run_id=self.run_id,
            event_type=event_type.value if isinstance(event_type, EventType) else str(event_type),
            timestamp=datetime.now(timezone.utc).isoformat(),
            data=data or {},
            seq=len(self.events),
        )
        self.events.append(evt)
        self._apply(evt)
        return evt

    def _apply(self, evt: PipelineEvent) -> None:
        """将单个事件应用到投影（状态机转移）。"""
        p = self._projection
        p.event_count = len(self.events)
        p.last_event_type = evt.event_type

        et = evt.event_type
        d = evt.data

        if et == EventType.PIPELINE_STARTED:
            p.status = "running"
            p.started_at = evt.timestamp
            p.requirement = d.get("requirement", "")

        elif et == EventType.PIPELINE_COMPLETED:
            p.status = "success"
            p.completed_at = evt.timestamp

        elif et == EventType.PIPELINE_FAILED:
            p.status = "failed"
            p.completed_at = evt.timestamp
            p.error = d.get("error")

        elif et == EventType.PIPELINE_BLOCKED:
            p.status = "blocked"
            p.completed_at = evt.timestamp
            p.error = d.get("reason")
            p.security_blocked = True

        elif et == EventType.PHASE_COMPLETED:
            phase = d.get("phase", "")
            if phase and phase not in p.phases_completed:
                p.phases_completed.append(phase)

        elif et == EventType.PHASE_FAILED:
            phase = d.get("phase", "")
            if phase and phase not in p.phases_failed:
                p.phases_failed.append(phase)

        elif et == EventType.AGENT_COMPLETED:
            agent = d.get("agent", "")
            if agent and agent not in p.agents_completed:
                p.agents_completed.append(agent)

        elif et == EventType.QUALITY_GATE_PASSED:
            p.quality_passed = True
            score = d.get("score")
            if score is not None:
                p.quality_scores.append(float(score))

        elif et == EventType.QUALITY_GATE_FAILED:
            p.quality_passed = False
            score = d.get("score")
            if score is not None:
                p.quality_scores.append(float(score))

        elif et == EventType.QUALITY_FIX_DONE:
            p.fix_iterations += 1

        elif et == EventType.SEARCH_CONTEXT_RETRIEVED:
            pass  # informational; projection status unchanged

        elif et == EventType.FIX_CONTEXT_INJECTED:
            pass  # informational; projection status unchanged

        elif et == EventType.HITL_APPROVAL_REQUESTED:
            p.hitl_pending = True

        elif et in (EventType.HITL_APPROVED, EventType.HITL_REJECTED):
            p.hitl_pending = False

        elif et == EventType.SECURITY_BLOCKED:
            p.security_blocked = True
            p.status = "blocked"

    # ── 读取 ─────────────────────────────────────────────────────────────────

    def project(self) -> Dict[str, Any]:
        """返回当前投影的只读字典视图。"""
        p = self._projection
        return {
            "run_id":           p.run_id,
            "status":           p.status,
            "started_at":       p.started_at,
            "completed_at":     p.completed_at,
            "requirement":      p.requirement,
            "phases_completed": list(p.phases_completed),
            "phases_failed":    list(p.phases_failed),
            "agents_completed": list(p.agents_completed),
            "quality_scores":   list(p.quality_scores),
            "quality_passed":   p.quality_passed,
            "fix_iterations":   p.fix_iterations,
            "hitl_pending":     p.hitl_pending,
            "security_blocked": p.security_blocked,
            "error":            p.error,
            "event_count":      p.event_count,
            "last_event_type":  p.last_event_type,
        }

    # ── 持久化 ───────────────────────────────────────────────────────────────

    def persist(self) -> Path:
        """
        将内存事件流刷写到磁盘。
        events.jsonl  — 追加写（保证幂等：先 truncate 再全量写入，适合单进程场景）
        execution_state.json — 覆盖写（只读投影，可随时从 events 重建）
        """
        run_dir = self.base_dir / self.run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        events_path = run_dir / "events.jsonl"
        events_path.write_text(
            "\n".join(json.dumps(e.to_dict(), ensure_ascii=False) for e in self.events),
            encoding="utf-8",
        )

        state_path = run_dir / "execution_state.json"
        state_path.write_text(
            json.dumps(self.project(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        return run_dir

    @classmethod
    def load(cls, run_id: str, base_dir: str = BASE_DIR) -> "PipelineEventStore":
        """从磁盘的 events.jsonl 恢复，重建投影（从事件流重放，不读 execution_state）。"""
        store = cls(run_id=run_id, base_dir=base_dir)
        events_path = Path(base_dir) / run_id / "events.jsonl"
        if not events_path.exists():
            return store
        for line in events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            evt = PipelineEvent.from_dict(json.loads(line))
            store.events.append(evt)
            store._apply(evt)
        return store

    @classmethod
    def list_runs(cls, base_dir: str = BASE_DIR) -> List[str]:
        """列出所有已持久化的 run_id。"""
        base = Path(base_dir)
        if not base.exists():
            return []
        return sorted(
            p.name for p in base.iterdir()
            if p.is_dir() and (p / "events.jsonl").exists()
        )
