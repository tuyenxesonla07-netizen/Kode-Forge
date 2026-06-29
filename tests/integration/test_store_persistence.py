# tests/integration/test_store_persistence.py

"""
Store 持久化测试。

覆盖:
- StoreDatabase: put/get/get_all/delete/clear/namespace隔离
- SpecStore + DB: 双写、回退读取、合并、clear
- SpecStore 无 DB: 向后兼容
- Pipeline 持久化: 完整 Pipeline 运行后 spec 持久化
"""

import os
import tempfile
from pathlib import Path

import pytest

from tools.stores.persistence import StoreDatabase
from tools.stores.spec_store import SpecStore, ModuleSpec, ComponentDef, StateMachineDef


# ─── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def tmp_db_path():
    """临时数据库路径（不依赖 TemporaryDirectory 自动清理）"""
    import uuid
    temp_dir = Path(tempfile.gettempdir()) / f"ccm_test_{uuid.uuid4().hex[:8]}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    db_path = str(temp_dir / "test_stores.db")
    yield db_path
    # 手动清理（确保 DB 连接已关闭）
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def db(tmp_db_path):
    """StoreDatabase 实例"""
    database = StoreDatabase(db_path=tmp_db_path)
    yield database
    database.close()


@pytest.fixture
def sample_spec():
    """示例 ModuleSpec"""
    return ModuleSpec(
        module_name="auth",
        components=[
            ComponentDef(name="AuthService", type="service", description="认证服务"),
            ComponentDef(name="TokenManager", type="service", description="令牌管理"),
        ],
        interfaces=[
            {"name": "login", "method": "POST", "path": "/auth/login"},
        ],
        acceptance_criteria=["用户可登录", "Token 自动刷新"],
        state_machine=StateMachineDef(
            states=["anonymous", "authenticated"],
            transitions=[{"from": "anonymous", "to": "authenticated", "trigger": "login"}],
        ),
        confidence=0.9,
        reasoning="JWT-based authentication",
    )


# ─── StoreDatabase 测试 ──────────────────────────────────


class TestStoreDatabase:
    """StoreDatabase 基础操作"""

    def test_put_and_get(self, db):
        db.put("test_type", "key1", {"data": "value1"})
        result = db.get("test_type", "key1")
        assert result == {"data": "value1"}

    def test_get_nonexistent(self, db):
        assert db.get("test_type", "nonexistent") is None

    def test_get_all(self, db):
        db.put("test_type", "key1", {"a": 1})
        db.put("test_type", "key2", {"b": 2})
        result = db.get_all("test_type")
        assert result == {"key1": {"a": 1}, "key2": {"b": 2}}

    def test_delete(self, db):
        db.put("test_type", "key1", {"data": "value"})
        assert db.delete("test_type", "key1") is True
        assert db.get("test_type", "key1") is None

    def test_delete_nonexistent(self, db):
        assert db.delete("test_type", "nonexistent") is False

    def test_clear(self, db):
        db.put("test_type", "key1", {"a": 1})
        db.put("test_type", "key2", {"b": 2})
        db.clear("test_type")
        assert db.get_all("test_type") == {}

    def test_namespace_isolation(self, db):
        """不同 store_type 数据隔离"""
        db.put("type_a", "key1", {"source": "a"})
        db.put("type_b", "key1", {"source": "b"})

        assert db.get("type_a", "key1") == {"source": "a"}
        assert db.get("type_b", "key1") == {"source": "b"}

    def test_overwrite(self, db):
        """覆盖已有 key"""
        db.put("test_type", "key1", {"v": 1})
        db.put("test_type", "key1", {"v": 2})
        assert db.get("test_type", "key1") == {"v": 2}

    def test_persistence_across_instances(self, tmp_db_path):
        """跨实例持久化"""
        db1 = StoreDatabase(db_path=tmp_db_path)
        db1.put("test_type", "key1", {"data": "persistent"})
        db1.close()

        db2 = StoreDatabase(db_path=tmp_db_path)
        result = db2.get("test_type", "key1")
        assert result == {"data": "persistent"}
        db2.close()


# ─── SpecStore + DB 测试 ──────────────────────────────────


class TestSpecStorePersistence:
    """SpecStore 带 DB 的双写"""

    def test_put_writes_to_both(self, db, sample_spec):
        store = SpecStore(db=db)
        store.put("auth", sample_spec)

        # 内存中有
        assert store.get("auth") is not None
        # DB 中也有
        db_data = db.get("module_spec", "auth")
        assert db_data is not None
        assert db_data["module_name"] == "auth"

    def test_get_fallback_to_db(self, tmp_db_path, sample_spec):
        """内存无数据时回退 DB"""
        # 先写入
        db1 = StoreDatabase(db_path=tmp_db_path)
        store1 = SpecStore(db=db1)
        store1.put("auth", sample_spec)
        db1.close()

        # 新建实例（内存为空），但共享 DB
        db2 = StoreDatabase(db_path=tmp_db_path)
        store2 = SpecStore(db=db2)

        # 应该从 DB 回退读取
        result = store2.get("auth")
        assert result is not None
        assert result.module_name == "auth"
        assert result.confidence == 0.9
        db2.close()

    def test_get_all_merges_memory_and_db(self, tmp_db_path):
        """get_all 合并内存和 DB"""
        db = StoreDatabase(db_path=tmp_db_path)
        store = SpecStore(db=db)

        spec1 = ModuleSpec(module_name="auth", confidence=0.8)
        spec2 = ModuleSpec(module_name="order", confidence=0.7)

        store.put("auth", spec1)
        db.put("module_spec", "order", {
            "module_name": "order",
            "components": [],
            "interfaces": [],
            "acceptance_criteria": [],
            "state_machine": None,
            "confidence": 0.7,
            "reasoning": "",
        })

        all_specs = store.get_all()
        assert "auth" in all_specs
        assert "order" in all_specs
        assert all_specs["order"].confidence == 0.7

    def test_clear_clears_both(self, db, sample_spec):
        store = SpecStore(db=db)
        store.put("auth", sample_spec)
        store.clear()

        assert store.get("auth") is None
        assert db.get("module_spec", "auth") is None

    def test_state_machine_round_trip(self, db, sample_spec):
        """状态机序列化/反序列化"""
        store = SpecStore(db=db)
        store.put("auth", sample_spec)

        # 从 DB 读取
        db2 = StoreDatabase(db_path=db._db_path)
        store2 = SpecStore(db=db2)
        result = store2.get("auth")

        assert result.state_machine is not None
        assert result.state_machine.states == ["anonymous", "authenticated"]
        assert len(result.state_machine.transitions) == 1

    def test_backward_compat_without_db(self):
        """不传 db 时完全向后兼容"""
        store = SpecStore()
        spec = ModuleSpec(module_name="auth", confidence=0.5)
        store.put("auth", spec)

        result = store.get("auth")
        assert result is not None
        assert result.module_name == "auth"
        assert len(store) == 1


# ─── Pipeline 持久化测试 ──────────────────────────────────


class TestPipelinePersistence:
    """完整 Pipeline 运行后 spec 持久化"""

    def test_pipeline_persists_specs(self, tmp_db_path):
        """Pipeline 运行后 specs 写入 DB"""
        from __init__ import ClaudeCodexMultiAgent

        pipeline = ClaudeCodexMultiAgent(llm_backend="mock", enable_hitl=False, enable_observability=False)
        # 替换为临时 DB
        pipeline._store_db.close()
        pipeline._store_db = StoreDatabase(db_path=tmp_db_path)
        pipeline.spec_store = SpecStore(db=pipeline._store_db)

        result = pipeline.run_full_pipeline("Build auth module with JWT")

        # 验证 Phase 1 有代码产出
        assert result["status"] == "success"
        assert len(result["phase1"]["code_artifact"]) > 0

        # 验证 DB 中有 spec 数据
        db_specs = pipeline._store_db.get_all("module_spec")
        assert len(db_specs) > 0
        pipeline._store_db.close()

    def test_pipeline_survives_restart(self, tmp_db_path):
        """Pipeline 重启后 specs 可从 DB 恢复"""
        from __init__ import ClaudeCodexMultiAgent

        # 第一次运行
        pipeline1 = ClaudeCodexMultiAgent(llm_backend="mock", enable_hitl=False, enable_observability=False)
        pipeline1._store_db.close()
        pipeline1._store_db = StoreDatabase(db_path=tmp_db_path)
        pipeline1.spec_store = SpecStore(db=pipeline1._store_db)
        result1 = pipeline1.run_full_pipeline("Build auth module")

        first_specs = pipeline1._store_db.get_all("module_spec")
        first_count = len(first_specs)
        assert first_count > 0
        pipeline1._store_db.close()

        # 第二次运行（新实例，共享 DB）
        pipeline2 = ClaudeCodexMultiAgent(llm_backend="mock", enable_hitl=False, enable_observability=False)
        pipeline2._store_db.close()
        pipeline2._store_db = StoreDatabase(db_path=tmp_db_path)
        pipeline2.spec_store = SpecStore(db=pipeline2._store_db)

        # 验证 spec 可从 DB 读取
        db_specs = pipeline2._store_db.get_all("module_spec")
        assert len(db_specs) == first_count
        pipeline2._store_db.close()
