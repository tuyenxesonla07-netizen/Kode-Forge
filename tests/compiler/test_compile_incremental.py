# tests/compiler/test_compile_incremental.py
"""
P1-2: 增量编译测试。

验证 compile_incremental() 只重新编译变更的模块，复用未变更模块的结果。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tools.compiler import PipelineCompiler, PipelineConfig


class TestCompileIncremental(unittest.TestCase):
    """PipelineCompiler.compile_incremental 测试"""

    def _make_schemas(self):
        return {
            "authentication": {
                "type": "object",
                "properties": {
                    "requirement": {"type": "string"},
                    "constraints": {"type": "array"},
                },
            },
            "data_processing": {
                "type": "object",
                "properties": {
                    "requirement": {"type": "string"},
                    "dependencies": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["authentication"]},
                    },
                },
            },
            "api_integration": {
                "type": "object",
                "properties": {
                    "requirement": {"type": "string"},
                },
            },
        }

    def _make_compiled(self):
        """创建初始编译结果"""
        compiler = PipelineCompiler()
        schemas = self._make_schemas()
        return compiler.compile(schemas, agents_config={}, project_name="test")

    def test_no_changes_reuses_results(self):
        """无变更时应复用所有结果"""
        compiled = self._make_compiled()
        compiler = PipelineCompiler()

        result = compiler.compile_incremental(
            self._make_schemas(), compiled, agents_config={}
        )

        # 模块数量不变
        assert len(result.module_schemas) == 3
        # 标记为增量编译
        assert result.metadata.get("incremental") is True
        # 变更列表为空
        assert result.metadata.get("changed_modules") == []
        assert result.metadata.get("deleted_modules") == []

    def test_changed_module_recompiles_only_that(self):
        """只变更一个模块时，只有该模块被重新编译"""
        compiled = self._make_compiled()
        compiler = PipelineCompiler()

        new_schemas = self._make_schemas()
        # 修改 data_processing
        new_schemas["data_processing"] = {
            "type": "object",
            "properties": {
                "requirement": {"type": "string"},
                "new_field": {"type": "integer"},
            },
        }

        result = compiler.compile_incremental(
            new_schemas, compiled, agents_config={}
        )

        # 只有 data_processing 被标记为变更
        assert result.metadata.get("changed_modules") == ["data_processing"]
        assert result.metadata.get("deleted_modules") == []
        # 模块数量不变
        assert len(result.module_schemas) == 3

    def test_added_module(self):
        """新增模块时应被完整编译"""
        compiled = self._make_compiled()
        compiler = PipelineCompiler()

        new_schemas = self._make_schemas()
        new_schemas["notification"] = {
            "type": "object",
            "properties": {"requirement": {"type": "string"}},
        }

        result = compiler.compile_incremental(
            new_schemas, compiled, agents_config={}
        )

        assert "notification" in result.metadata.get("changed_modules", [])
        assert len(result.module_schemas) == 4
        assert "notification" in result.context_strategies
        assert "notification" in result.fix_templates

    def test_deleted_module(self):
        """删除模块时应从结果中移除"""
        compiled = self._make_compiled()
        compiler = PipelineCompiler()

        new_schemas = self._make_schemas()
        del new_schemas["api_integration"]

        result = compiler.compile_incremental(
            new_schemas, compiled, agents_config={}
        )

        assert "api_integration" in result.metadata.get("deleted_modules", [])
        assert "api_integration" not in result.module_schemas
        assert "api_integration" not in result.context_strategies
        assert len(result.module_schemas) == 2

    def test_implementation_order_updated(self):
        """implementation_order 应反映最新模块集合"""
        compiled = self._make_compiled()
        compiler = PipelineCompiler()

        new_schemas = self._make_schemas()
        new_schemas["notification"] = {
            "type": "object",
            "properties": {"requirement": {"type": "string"}},
        }

        result = compiler.compile_incremental(
            new_schemas, compiled, agents_config={}
        )

        # 所有模块都在 implementation_order 中
        for name in new_schemas:
            assert name in result.implementation_order

    def test_multiple_changed_modules(self):
        """多个模块同时变更"""
        compiled = self._make_compiled()
        compiler = PipelineCompiler()

        new_schemas = self._make_schemas()
        new_schemas["authentication"]["properties"]["new_field"] = {"type": "string"}
        new_schemas["api_integration"]["properties"]["version"] = {"type": "string"}

        result = compiler.compile_incremental(
            new_schemas, compiled, agents_config={}
        )

        changed = result.metadata.get("changed_modules", [])
        assert "authentication" in changed
        assert "api_integration" in changed
        assert "data_processing" not in changed

    def test_empty_previous_compiled(self):
        """previous_compiled 为空模块时退化为完整编译"""
        compiler = PipelineCompiler()

        # 创建一个空的 compiled
        empty_compiled = compiler.compile({}, agents_config={})

        schemas = self._make_schemas()
        result = compiler.compile_incremental(
            schemas, empty_compiled, agents_config={}
        )

        # 所有模块都是新增
        assert len(result.module_schemas) == 3
        assert set(result.metadata.get("changed_modules", [])) == set(schemas.keys())


if __name__ == "__main__":
    unittest.main()
