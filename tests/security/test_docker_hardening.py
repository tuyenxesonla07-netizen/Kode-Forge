"""Phase 7 tests: Docker hardening (Gaps 31-38)."""

import os
import pytest


# ===========================================================================
# Gap 31: Read-only filesystem
# ===========================================================================

class TestGap31_ReadOnlyFilesystem:
    """Gap 31: No read-only filesystem in docker-compose."""

    def test_docker_compose_prod_exists(self):
        assert os.path.exists("docker-compose.prod.yml")

    def test_read_only_filesystem(self):
        with open("docker-compose.prod.yml", encoding="utf-8") as f:
            content = f.read()
        assert "read_only: true" in content


# ===========================================================================
# Gap 32: Capability dropping
# ===========================================================================

class TestGap32_CapDrop:
    """Gap 32: No capability dropping."""

    def test_cap_drop_all(self):
        with open("docker-compose.prod.yml", encoding="utf-8") as f:
            content = f.read()
        assert "cap_drop" in content
        assert "ALL" in content


# ===========================================================================
# Gap 33: Resource limits
# ===========================================================================

class TestGap33_ResourceLimits:
    """Gap 33: No resource limits."""

    def test_memory_limit(self):
        with open("docker-compose.prod.yml", encoding="utf-8") as f:
            content = f.read()
        assert "memory" in content.lower()

    def test_cpu_limit(self):
        with open("docker-compose.prod.yml", encoding="utf-8") as f:
            content = f.read()
        assert "cpus" in content.lower()


# ===========================================================================
# Gap 34: Seccomp / security options
# ===========================================================================

class TestGap34_Seccomp:
    """Gap 34: No seccomp profile."""

    def test_no_new_privileges(self):
        with open("docker-compose.prod.yml", encoding="utf-8") as f:
            content = f.read()
        assert "no-new-privileges" in content


# ===========================================================================
# Gap 35: Dev tools in production
# ===========================================================================

class TestGap35_DevToolsInProd:
    """Gap 35: Dev tools in production image."""

    def test_multi_stage_dockerfile(self):
        assert os.path.exists("Dockerfile.production")
        with open("Dockerfile.production", encoding="utf-8") as f:
            content = f.read()
        # Multi-stage build
        assert "AS " in content
        # No dev dependencies in production stage
        lines = content.split("\n")
        prod_stage = False
        for line in lines:
            if "AS production" in line:
                prod_stage = True
            if prod_stage and "pip install" in line:
                # Should only install from requirements.txt
                assert "requirements.txt" in line
                assert "pytest" not in line.lower()
                assert "ruff" not in line.lower()


# ===========================================================================
# Gap 36: Image pinning (documented)
# ===========================================================================

class TestGap36_ImagePinning:
    """Gap 36: Image not pinned to digest (documented as recommendation)."""

    def test_docker_compose_prod_exists(self):
        import os
        assert os.path.exists("docker-compose.prod.yml")


# ===========================================================================
# Gap 37: Dependency lock file
# ===========================================================================

class TestGap37_LockFile:
    """Gap 37: No dependency lock file."""

    def test_requirements_txt_exists(self):
        assert os.path.exists("requirements.txt")
        with open("requirements.txt", encoding="utf-8") as f:
            content = f.read()
        # Should have version specifiers (== or >=)
        assert "==" in content or ">=" in content

    def test_requirements_dev_exists(self):
        assert os.path.exists("requirements-dev.txt")


# ===========================================================================
# Gap 38: Network isolation
# ===========================================================================

class TestGap38_NetworkIsolation:
    """Gap 38: No network isolation."""

    def test_networks_defined(self):
        with open("docker-compose.prod.yml", encoding="utf-8") as f:
            content = f.read()
        assert "networks:" in content

    def test_internal_network(self):
        with open("docker-compose.prod.yml", encoding="utf-8") as f:
            content = f.read()
        assert "internal" in content


# ===========================================================================
# Bonus: Docker files structure
# ===========================================================================

class TestDockerStructure:
    """Verify Docker-related files are properly structured."""

    def test_dockerfile_production_exists(self):
        assert os.path.exists("Dockerfile.production")

    def test_docker_compose_prod_exists(self):
        assert os.path.exists("docker-compose.prod.yml")

    def test_nginx_config_exists(self):
        assert os.path.exists("docker/nginx/nginx.conf")

    def test_ssl_config_exists(self):
        assert os.path.exists("docker/nginx/ssl.conf")

    def test_dockerignore_exists(self):
        assert os.path.exists(".dockerignore")

    def test_dockerignore_excludes_env(self):
        with open(".dockerignore", encoding="utf-8") as f:
            content = f.read()
        assert ".env" in content

    def test_dockerignore_excludes_git(self):
        with open(".dockerignore", encoding="utf-8") as f:
            content = f.read()
        assert ".git" in content

    def test_dockerignore_excludes_data(self):
        with open(".dockerignore", encoding="utf-8") as f:
            content = f.read()
        assert "data/" in content

    def test_nginx_config_has_tls(self):
        with open("docker/nginx/nginx.conf", encoding="utf-8") as f:
            content = f.read()
        assert "TLS" in content or "tls" in content

    def test_nginx_config_has_security_headers(self):
        with open("docker/nginx/nginx.conf", encoding="utf-8") as f:
            content = f.read()
        assert "X-Content-Type-Options" in content
        assert "X-Frame-Options" in content

    def test_production_dockerfile_non_root(self):
        with open("Dockerfile.production", encoding="utf-8") as f:
            content = f.read()
        assert "USER appuser" in content or "useradd" in content
