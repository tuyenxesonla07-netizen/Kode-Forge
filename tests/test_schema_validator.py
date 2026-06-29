# tests/test_schema_validator.py
"""
P2-2: Schema 验证工具测试。
"""
import json
import os
import tempfile
import unittest

from tools.schema_validator import (
    ValidationReport,
    validate_agents_schemas_consistency,
    validate_all,
    validate_dependency_references,
    validate_json_schemas,
)


class TestValidationReport(unittest.TestCase):
    """ValidationReport 数据类测试"""

    def test_empty_report_is_valid(self):
        report = ValidationReport()
        assert report.is_valid
        assert len(report.errors) == 0
        assert len(report.warnings) == 0

    def test_report_with_errors_is_invalid(self):
        report = ValidationReport()
        report.add("error", "something wrong")
        assert not report.is_valid
        assert len(report.errors) == 1

    def test_report_with_only_warnings_is_valid(self):
        report = ValidationReport()
        report.add("warning", "just a warning")
        assert report.is_valid
        assert len(report.warnings) == 1
        assert len(report.errors) == 0

    def test_merge_reports(self):
        r1 = ValidationReport()
        r1.add("error", "err1")
        r2 = ValidationReport()
        r2.add("warning", "warn1")
        r1.merge(r2)
        assert len(r1.issues) == 2
        assert not r1.is_valid

    def test_summary_contains_counts(self):
        report = ValidationReport()
        report.add("error", "bad")
        report.add("warning", "careful")
        summary = report.summary()
        assert "1 error" in summary
        assert "1 warning" in summary


class TestValidateJsonSchemas(unittest.TestCase):
    """validate_json_schemas 测试"""

    def test_missing_directory(self):
        report = validate_json_schemas("/nonexistent/path")
        assert not report.is_valid
        assert any("not found" in i.message for i in report.issues)

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = validate_json_schemas(tmpdir)
            assert report.is_valid
            assert any("No JSON Schema" in i.message for i in report.issues)

    def test_valid_schema_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建合法的 input schema
            input_schema = {
                "type": "object",
                "required": ["requirement"],
                "properties": {
                    "requirement": {"type": "string"},
                    "dependencies": {
                        "type": "array",
                        "items": {"type": "string", "enum": []},
                    },
                },
            }
            with open(os.path.join(tmpdir, "auth_input.json"), "w") as f:
                json.dump(input_schema, f)

            # 创建合法的 output schema
            output_schema = {
                "type": "object",
                "properties": {
                    "module_spec": {"type": "object"},
                },
            }
            with open(os.path.join(tmpdir, "auth_output.json"), "w") as f:
                json.dump(output_schema, f)

            report = validate_json_schemas(tmpdir)
            assert report.is_valid

    def test_invalid_json_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "broken.json"), "w") as f:
                f.write("{invalid json")

            report = validate_json_schemas(tmpdir)
            assert not report.is_valid
            assert any("Invalid JSON" in i.message for i in report.issues)

    def test_output_schema_missing_module_spec(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_output = {"type": "object", "properties": {"wrong_field": {}}}
            with open(os.path.join(tmpdir, "mod_output.json"), "w") as f:
                json.dump(bad_output, f)

            report = validate_json_schemas(tmpdir)
            assert not report.is_valid
            assert any("module_spec" in i.message for i in report.issues)


class TestValidateAgentsSchemasConsistency(unittest.TestCase):
    """validate_agents_schemas_consistency 测试"""

    def _write_yaml(self, path: str, content: str):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def _write_schema(self, dirpath: str, name: str, is_input: bool = True):
        suffix = "_input" if is_input else "_output"
        data = {"type": "object", "properties": {}}
        if not is_input:
            data["properties"]["module_spec"] = {"type": "object"}
        with open(os.path.join(dirpath, f"{name}{suffix}.json"), "w") as f:
            json.dump(data, f)

    def test_all_consistent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            schemas_dir = os.path.join(tmpdir, "schemas")
            os.makedirs(schemas_dir)

            # 创建 schemas
            self._write_schema(schemas_dir, "auth", True)
            self._write_schema(schemas_dir, "auth", False)

            # 创建对应的 agents.yaml
            agents_yaml = """
agents:
  expert_auth:
    role: expert
    module: auth
    version: "1.0.0"
"""
            agents_path = os.path.join(tmpdir, "agents.yaml")
            self._write_yaml(agents_path, agents_yaml)

            report = validate_agents_schemas_consistency(agents_path, schemas_dir)
            assert report.is_valid

    def test_missing_input_schema(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            schemas_dir = os.path.join(tmpdir, "schemas")
            os.makedirs(schemas_dir)

            # 只创建 output schema
            self._write_schema(schemas_dir, "auth", False)

            agents_yaml = """
agents:
  expert_auth:
    role: expert
    module: auth
"""
            agents_path = os.path.join(tmpdir, "agents.yaml")
            self._write_yaml(agents_path, agents_yaml)

            report = validate_agents_schemas_consistency(agents_path, schemas_dir)
            assert not report.is_valid
            assert any("missing input schema" in i.message for i in report.issues)

    def test_schema_without_agent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            schemas_dir = os.path.join(tmpdir, "schemas")
            os.makedirs(schemas_dir)

            # 创建 orphan schema（无对应 agent）
            self._write_schema(schemas_dir, "orphan", True)
            self._write_schema(schemas_dir, "orphan", False)
            # 同时创建 auth 的 schema（对应 expert_auth）
            self._write_schema(schemas_dir, "auth", True)
            self._write_schema(schemas_dir, "auth", False)

            agents_yaml = """
agents:
  expert_auth:
    role: expert
    module: auth
"""
            agents_path = os.path.join(tmpdir, "agents.yaml")
            self._write_yaml(agents_path, agents_yaml)

            report = validate_agents_schemas_consistency(agents_path, schemas_dir)
            # orphan schema 是 warning 不是 error
            assert report.is_valid
            assert any("orphan" in i.message for i in report.warnings)


class TestValidateDependencyReferences(unittest.TestCase):
    """validate_dependency_references 测试"""

    def test_valid_dependencies(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            schemas_dir = os.path.join(tmpdir, "schemas")
            os.makedirs(schemas_dir)

            # auth 不依赖其他模块
            auth_input = {
                "type": "object",
                "properties": {
                    "requirement": {"type": "string"},
                    "dependencies": {
                        "type": "array",
                        "items": {"type": "string", "enum": []},
                    },
                },
            }
            with open(os.path.join(schemas_dir, "auth_input.json"), "w") as f:
                json.dump(auth_input, f)
            with open(os.path.join(schemas_dir, "auth_output.json"), "w") as f:
                json.dump({"type": "object"}, f)

            # data 依赖 auth
            data_input = {
                "type": "object",
                "properties": {
                    "requirement": {"type": "string"},
                    "dependencies": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["auth"]},
                    },
                },
            }
            with open(os.path.join(schemas_dir, "data_input.json"), "w") as f:
                json.dump(data_input, f)
            with open(os.path.join(schemas_dir, "data_output.json"), "w") as f:
                json.dump({"type": "object"}, f)

            agents_path = os.path.join(tmpdir, "agents.yaml")
            with open(agents_path, "w") as f:
                f.write("agents:\n  expert_auth:\n    role: expert\n    module: auth\n  expert_data:\n    role: expert\n    module: data\n")

            report = validate_dependency_references(agents_path, schemas_dir)
            assert report.is_valid

    def test_unknown_dependency(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            schemas_dir = os.path.join(tmpdir, "schemas")
            os.makedirs(schemas_dir)

            # data 依赖一个不存在的模块 "ghost"
            data_input = {
                "type": "object",
                "properties": {
                    "requirement": {"type": "string"},
                    "dependencies": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["ghost"]},
                    },
                },
            }
            with open(os.path.join(schemas_dir, "data_input.json"), "w") as f:
                json.dump(data_input, f)
            with open(os.path.join(schemas_dir, "data_output.json"), "w") as f:
                json.dump({"type": "object"}, f)

            agents_path = os.path.join(tmpdir, "agents.yaml")
            with open(agents_path, "w") as f:
                f.write("agents:\n  expert_data:\n    role: expert\n    module: data\n")

            report = validate_dependency_references(agents_path, schemas_dir)
            # 未知依赖是 warning
            assert report.is_valid
            assert any("ghost" in i.message for i in report.warnings)


class TestValidateAll(unittest.TestCase):
    """validate_all 集成测试"""

    def test_validate_real_config(self):
        """验证项目自带的配置（应该在项目根目录下通过）"""
        # 从项目根目录运行
        report = validate_all("config")
        # 项目自带配置应该是有效的
        assert report.is_valid, f"Config validation failed:\n{report.summary()}"

    def test_validate_with_temp_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            schemas_dir = os.path.join(tmpdir, "schemas")
            os.makedirs(schemas_dir)

            # auth 模块
            with open(os.path.join(schemas_dir, "auth_input.json"), "w") as f:
                json.dump({
                    "type": "object",
                    "required": ["requirement"],
                    "properties": {"requirement": {"type": "string"}},
                }, f)
            with open(os.path.join(schemas_dir, "auth_output.json"), "w") as f:
                json.dump({
                    "type": "object",
                    "properties": {"module_spec": {"type": "object"}},
                }, f)

            with open(os.path.join(tmpdir, "agents.yaml"), "w") as f:
                f.write("agents:\n  expert_auth:\n    role: expert\n    module: auth\n    version: '1.0.0'\n")

            report = validate_all(tmpdir)
            assert report.is_valid


if __name__ == "__main__":
    unittest.main()
