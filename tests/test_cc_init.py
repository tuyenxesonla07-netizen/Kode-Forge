"""Tests for cc_init — project scaffold generator."""

import json
import os
import shutil
import tempfile

import pytest

from tools.cc_init import (
    _make_input_schema,
    _make_output_schema,
    _make_agents_yaml,
    _make_pipeline_yaml,
    _make_readme,
    scaffold,
    DEFAULT_MODULES,
)


class TestMakeInputSchema:
    """Tests for _make_input_schema template generator."""

    def test_returns_dict(self):
        result = _make_input_schema("auth")
        assert isinstance(result, dict)

    def test_has_json_schema_key(self):
        result = _make_input_schema("auth")
        assert "$schema" in result

    def test_title_contains_module_name(self):
        result = _make_input_schema("data_processing")
        assert "Data Processing" in result["title"]

    def test_required_fields(self):
        result = _make_input_schema("auth")
        assert "requirement" in result["required"]
        assert "constraints" in result["required"]

    def test_has_tech_stack(self):
        result = _make_input_schema("auth")
        assert "tech_stack" in result["properties"]

    def test_has_acceptance_criteria(self):
        result = _make_input_schema("auth")
        assert "acceptance_criteria" in result["properties"]


class TestMakeOutputSchema:
    """Tests for _make_output_schema template generator."""

    def test_returns_dict(self):
        result = _make_output_schema("auth")
        assert isinstance(result, dict)

    def test_has_module_spec(self):
        result = _make_output_schema("auth")
        spec = result["properties"]["module_spec"]
        assert "components" in spec["properties"]
        assert "interfaces" in spec["properties"]

    def test_has_confidence(self):
        result = _make_output_schema("auth")
        assert "confidence" in result["properties"]


class TestMakeAgentsYaml:
    """Tests for _make_agents_yaml template generator."""

    def test_contains_all_modules(self):
        yaml_str = _make_agents_yaml(["auth", "api", "data"])
        assert "expert_auth" in yaml_str
        assert "expert_api" in yaml_str
        assert "expert_data" in yaml_str

    def test_has_settings(self):
        yaml_str = _make_agents_yaml(["auth"])
        assert "settings:" in yaml_str
        assert "auto_discover" in yaml_str


class TestMakePipelineYaml:
    """Tests for _make_pipeline_yaml template generator."""

    def test_has_quality_gates(self):
        yaml_str = _make_pipeline_yaml()
        assert "quality_gates" in yaml_str

    def test_has_retry_policy(self):
        yaml_str = _make_pipeline_yaml()
        assert "retry_policy" in yaml_str


class TestMakeReadme:
    """Tests for _make_readme template generator."""

    def test_contains_project_name(self):
        readme = _make_readme("MyProject", ["auth", "api"])
        assert "MyProject" in readme

    def test_contains_module_list(self):
        readme = _make_readme("Test", ["auth", "data_processing"])
        assert "auth" in readme
        assert "data_processing" in readme


class TestScaffold:
    """Tests for the scaffold() function."""

    def test_creates_project_dir(self, tmp_path):
        result = scaffold("my-test", str(tmp_path))
        assert os.path.isdir(result)
        assert result.endswith("my-test")

    def test_creates_schemas(self, tmp_path):
        result = scaffold("my-test", str(tmp_path), modules=["auth", "api"])
        schemas_dir = os.path.join(result, "config", "schemas")
        assert os.path.isdir(schemas_dir)
        assert os.path.exists(os.path.join(schemas_dir, "auth_input.json"))
        assert os.path.exists(os.path.join(schemas_dir, "auth_output.json"))
        assert os.path.exists(os.path.join(schemas_dir, "api_input.json"))
        assert os.path.exists(os.path.join(schemas_dir, "api_output.json"))

    def test_creates_agents_yaml(self, tmp_path):
        result = scaffold("my-test", str(tmp_path))
        assert os.path.exists(os.path.join(result, "config", "agents.yaml"))

    def test_creates_pipeline_yaml(self, tmp_path):
        result = scaffold("my-test", str(tmp_path))
        assert os.path.exists(os.path.join(result, "config", "pipeline.yaml"))

    def test_creates_readme(self, tmp_path):
        result = scaffold("my-test", str(tmp_path))
        assert os.path.exists(os.path.join(result, "README.md"))

    def test_schema_is_valid_json(self, tmp_path):
        result = scaffold("my-test", str(tmp_path), modules=["auth"])
        input_path = os.path.join(result, "config", "schemas", "auth_input.json")
        with open(input_path, encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, dict)
        assert "properties" in data

    def test_raises_on_existing_dir(self, tmp_path):
        scaffold("my-test", str(tmp_path))
        with pytest.raises(FileExistsError):
            scaffold("my-test", str(tmp_path))

    def test_default_modules(self, tmp_path):
        result = scaffold("my-test", str(tmp_path))
        schemas_dir = os.path.join(result, "config", "schemas")
        for module in DEFAULT_MODULES:
            assert os.path.exists(os.path.join(schemas_dir, f"{module}_input.json"))

    def test_custom_modules_via_comma(self, tmp_path):
        result = scaffold("my-test", str(tmp_path), modules=["user", "payment"])
        schemas_dir = os.path.join(result, "config", "schemas")
        assert os.path.exists(os.path.join(schemas_dir, "user_input.json"))
        assert os.path.exists(os.path.join(schemas_dir, "payment_input.json"))

    def teardown_method(self):
        """Clean up any test projects in current directory."""
        for d in ["my-test", "test-demo", "custom"]:
            if os.path.exists(d):
                shutil.rmtree(d)
