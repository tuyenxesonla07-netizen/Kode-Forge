# tests/integration/test_code_writer.py

"""
CodeWriter 测试。

覆盖:
- write_code_artifacts: 单模块/多模块/空跳过/自动创建目录/init/备份/dry_run
- 从 Pipeline 端到端写入文件
"""

import os
import tempfile
from pathlib import Path

import pytest

from agents.supervisor.agent_executor import write_code_artifacts, CodeWriterConfig


# ─── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def sample_code():
    """示例代码"""
    return {
        "auth": '"""Authentication module."""\n\nclass AuthService:\n    """Handles authentication."""\n    pass\n',
        "order": '"""Order module."""\n\nclass OrderService:\n    """Manages orders."""\n    pass\n',
    }


@pytest.fixture
def tmp_dir():
    """临时目录"""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


# ─── 基础功能测试 ─────────────────────────────────────────


class TestWriteCodeArtifacts:
    """write_code_artifacts 基础功能"""

    def test_single_module(self, tmp_dir, sample_code):
        config = CodeWriterConfig(base_dir=str(tmp_dir))
        written = write_code_artifacts({"auth": sample_code["auth"]}, config)

        assert len(written) == 1
        assert (tmp_dir / "auth" / "service.py").exists()
        content = (tmp_dir / "auth" / "service.py").read_text()
        assert "AuthService" in content

    def test_multiple_modules(self, tmp_dir, sample_code):
        config = CodeWriterConfig(base_dir=str(tmp_dir))
        written = write_code_artifacts(sample_code, config)

        assert len(written) == 2
        assert (tmp_dir / "auth" / "service.py").exists()
        assert (tmp_dir / "order" / "service.py").exists()

    def test_skip_empty_code(self, tmp_dir):
        """空字符串应被跳过"""
        config = CodeWriterConfig(base_dir=str(tmp_dir))
        written = write_code_artifacts({"auth": "", "order": "valid code"}, config)

        assert len(written) == 1
        assert "order" in written[0]
        assert not (tmp_dir / "auth" / "service.py").exists()

    def test_skip_whitespace_only(self, tmp_dir):
        """纯空白代码应被跳过"""
        config = CodeWriterConfig(base_dir=str(tmp_dir))
        written = write_code_artifacts({"auth": "   \n\n  "}, config)

        assert len(written) == 0

    def test_auto_create_directory(self, tmp_dir, sample_code):
        """自动创建不存在的目录"""
        config = CodeWriterConfig(base_dir=str(tmp_dir))
        write_code_artifacts(sample_code, config)

        assert (tmp_dir / "auth").is_dir()
        assert (tmp_dir / "order").is_dir()

    def test_auto_create_init(self, tmp_dir, sample_code):
        """自动创建 __init__.py"""
        config = CodeWriterConfig(base_dir=str(tmp_dir), create_init_files=True)
        write_code_artifacts(sample_code, config)

        init_path = tmp_dir / "auth" / "__init__.py"
        assert init_path.exists()
        content = init_path.read_text()
        assert "auth" in content

    def test_no_init_when_disabled(self, tmp_dir, sample_code):
        """禁用 create_init_files 时不创建 __init__.py"""
        config = CodeWriterConfig(base_dir=str(tmp_dir), create_init_files=False)
        write_code_artifacts(sample_code, config)

        assert not (tmp_dir / "auth" / "__init__.py").exists()

    def test_backup_existing(self, tmp_dir, sample_code):
        """备份已有文件"""
        # 先创建文件
        (tmp_dir / "auth").mkdir(parents=True, exist_ok=True)
        existing = tmp_dir / "auth" / "service.py"
        existing.write_text("# old content\n")

        config = CodeWriterConfig(base_dir=str(tmp_dir), backup_existing=True)
        write_code_artifacts(sample_code, config)

        # 检查备份文件存在
        backups = list((tmp_dir / "auth").glob("*.bak"))
        assert len(backups) == 1
        assert "old content" in backups[0].read_text()

    def test_no_backup_when_disabled(self, tmp_dir, sample_code):
        """禁用备份时不备份"""
        (tmp_dir / "auth").mkdir(parents=True, exist_ok=True)
        existing = tmp_dir / "auth" / "service.py"
        existing.write_text("# old content\n")

        config = CodeWriterConfig(base_dir=str(tmp_dir), backup_existing=False)
        write_code_artifacts(sample_code, config)

        backups = list((tmp_dir / "auth").glob("*.bak"))
        assert len(backups) == 0

    def test_dry_run(self, tmp_dir, sample_code):
        """dry_run 模式不实际写入"""
        config = CodeWriterConfig(base_dir=str(tmp_dir), dry_run=True)
        written = write_code_artifacts(sample_code, config)

        assert len(written) == 2
        assert not (tmp_dir / "auth" / "service.py").exists()

    def test_custom_template(self, tmp_dir):
        """自定义路径模板"""
        config = CodeWriterConfig(
            base_dir=str(tmp_dir),
            module_template="{base_dir}/{module}/handler.py",
        )
        written = write_code_artifacts({"auth": "code"}, config)

        assert (tmp_dir / "auth" / "handler.py").exists()

    def test_returns_written_paths(self, tmp_dir, sample_code):
        """返回写入的文件路径列表"""
        config = CodeWriterConfig(base_dir=str(tmp_dir))
        written = write_code_artifacts(sample_code, config)

        assert all(isinstance(p, str) for p in written)
        assert all("service.py" in p for p in written)


# ─── 端到端 Pipeline → 文件写入测试 ──────────────────────


class TestWriteCodeArtifactsFromPipeline:
    """从完整 Pipeline 写入文件"""

    def test_pipeline_writes_files(self, tmp_dir):
        """模拟 Pipeline 输出写入文件"""
        code_artifact = {
            "auth": '"""Auth module."""\nclass AuthService:\n    pass\n',
            "product": '"""Product module."""\nclass ProductService:\n    pass\n',
        }
        config = CodeWriterConfig(base_dir=str(tmp_dir))
        written = write_code_artifacts(code_artifact, config)

        assert len(written) == 2
        for path in written:
            assert Path(path).exists()

    def test_pipeline_overwrites_existing(self, tmp_dir):
        """Pipeline 覆盖已有文件并备份"""
        # 已有文件
        (tmp_dir / "auth").mkdir(parents=True, exist_ok=True)
        (tmp_dir / "auth" / "service.py").write_text("# legacy code\n")

        code_artifact = {"auth": '"""Auth module."""\nclass AuthService:\n    pass\n'}
        config = CodeWriterConfig(base_dir=str(tmp_dir))
        written = write_code_artifacts(code_artifact, config)

        content = (tmp_dir / "auth" / "service.py").read_text()
        assert "AuthService" in content
        assert "# legacy" not in content
