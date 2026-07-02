$Summary

这是 KodeForge GitHub Release 的完整方案，目标：一条 tag 打下去，**同时产出 5 种产物**自动挂到 Release 页面：

```
📦 KodeForge vX.Y.Z Release
├── 🐳 kodeforge:latest        (Docker image, ghcr.io)
├── 🪟 kodeforge-vX.Y.Z-windows-x64.zip    (PyInstaller 单文件)
├── 🍎 kodeforge-vX.Y.Z-macos-x64.zip      (PyInstaller 单文件)
├── 🐧 kodeforge-vX.Y.Z-linux-x64.tar.gz   (PyInstaller 单文件)
└── 📄 kodeforge-vX.Y.Z-py3-none-any.whl   (标准 Python wheel)
```

---

## 1. 技术选型决策

| 工具 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| **Nuitka** | 编译成 C，启动快，反编译难度高 | 编译耗时极长（CI timeout 风险），对动态 import 的包装层多 | ❌ |
| **cx_Freeze** | 成熟，支持跨平台的目录打包 | 仍是字节码，安全性不高；较少维护 | ❌ |
| **PyInstaller** | 生态最广、兼容最好、PyPI 选择最多；单文件/目录两种模式 | 字节码不加密（但这不是商业软件，不需要） | ✅ |
| **PyApp / cargo-packager** | Rust 重写，包体积小 | 生态比 PyInstaller 小很多 | ⚠️ |

**最终选择 PyInstaller**，原因：纯 Python 项目单文件输出，.ZERO 学习成本，GitHub Actions 有超过 100 万现成模板，几乎不会碰到未知坑。

---

## 2. PyInstaller 关键配置说明

```bash
pyinstaller \
    --onefile \                       # 单文件模式（也可选 --onedir）
    --name kodeforge \               # 输出文件名
    --console \                       # 控制台程序（非 GUI）
    --collect-all tools \             # 收集整个包（含动态 import）
    --collect-data config \           # 打包 JSON/YAML 配置文件
    --add-data "config:config" \      # 运行时解压到临时目录
    --hidden-import=tools.cc_cli \    # 显式补漏（保底）
```

**为什么需要 `--collect-all`？**

KodeForge 使用了大量动态 import：
- `tools.rag.*` 在运行时按 provider 选择加载
- `agents.experts` 基于 schema 自动发现
- `config/schemas/*.json` 是运行时加载的配置文件

只用 `--hidden-import` 不够：`--hidden-import` 只声明模块，不打包子模块。
`--collect-all tools` 会把整个 `tools/` 包的所有 .py 文件一起打包。

**配置文件如何打包？**

`--add-data "config:config"` 在运行时 PyInstaller 会把 config 目录解压到临时目录，
程序启动时 `sys._MEIPASS` 指向这个临时目录，我们的 `cc_cli.main()` 需要兼容这个路径。

见下方 `scripts/pyinstaller_runtime.py`。

---

## 3. 运行时适配（关键且容易被忽略）

```python
# scripts/pyinstaller_runtime.py
import sys
from pathlib import Path


def get_base_dir() -> Path:
    """
    兼容 PyInstaller 单文件模式：
    - PyInstaller 运行时：sys._MEIPASS 指向解压目录
    - 正常 Python 运行时：使用脚本所在目录
    """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # PyInstaller 把内容解压到临时目录，配置文件在这里
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
CONFIG_DIR = BASE_DIR / "config"
```

**注意**：如果你的代码里有写死的 `Path("config/...")` 或 `os.path.join(os.getcwd(), "config")`，
在 PyInstaller 单文件模式下会出错（因为 cwd 不是解压目录）。需要用 `get_base_dir()` 统一。

这是本项目目前已经有 `config/` 配置加载代码需要兼容的地方。

---

## 4. GitHub Actions 完整 workflow

```yaml
# .github/workflows/release.yml
name: Release

on:
  push:
    tags:
      - 'v*'

permissions:
  contents: write       # action-gh-release 需要
  packages: write       # docker push 需要

jobs:
  ######################################################################
  # 阶段 1：测试 + 类型检查 (Ubuntu, 只执行一次)
  ######################################################################
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'

      - name: Install
        run: |
          pip install -r requirements-dev.txt
          pip install -e .

      - name: Lint
        run: ruff check tools/ agents/ --select N999,E402

      - name: Test
        run: python -m pytest tests/ -x -q --tb=short

  ######################################################################
  # 阶段 2：跨平台构建（3 个并行 job）
  ######################################################################
  build_windows:
    needs: test
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'

      - name: Install
        run: |
          pip install pyinstaller
          pip install -r requirements.txt

      - name: Build (onedir)
        run: pyinstaller spec/windows.spec --distpath dist/ --workpath build/

      - name: Zip
        shell: pwsh
        run: |
          Compress-Archive -Path dist/kodeforge/* -DestinationPath kodeforge-${{ github.ref_name }}-windows-x64.zip

      - uses: actions/upload-artifact@v4
        with:
          name: release-windows
          path: kodeforge-*.zip

  build_macos:
    needs: test
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'

      - name: Install
        run: |
          pip install pyinstaller
          pip install -r requirements.txt

      - name: Build (onedir)
        run: pyinstaller spec/macos.spec --distpath dist/ --workpath build/

      - name: Zip
        run: |
          cd dist && zip -r ../kodeforge-${{ github.ref_name }}-macos-x64.zip kodeforge/

      - uses: actions/upload-artifact@v4
        with:
          name: release-macos
          path: kodeforge-*.zip

  build_linux:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'

      - name: Install
        run: |
          pip install pyinstaller
          pip install -r requirements.txt

      - name: Build (onedir)
        run: pyinstaller spec/linux.spec --distpath dist/ --workpath build/

      - name: Tar
        run: |
          cd dist && tar czf ../kodeforge-${{ github.ref_name }}-linux-x64.tar.gz kodeforge/

      - uses: actions/upload-artifact@v4
        with:
          name: release-linux
          path: kodeforge-*.tar.gz

  build_wheel:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install build tools
        run: pip install build

      - name: Build wheel
        run: python -m build --wheel

      - uses: actions/upload-artifact@v4
        with:
          name: release-wheel
          path: dist/*.whl

  ######################################################################
  # 阶段 3：Docker（并行）
  ######################################################################
  build_docker:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: docker/setup-buildx-action@v3

      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - uses: docker/metadata-action@v5
        id: meta
        with:
          images: ghcr.io/${{ github.repository }}
          tags: |
            type=semver,pattern={{version}}
            type=raw,value=latest

      - uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

  ######################################################################
  # 阶段 4：把产物全部挂到 Release 页面
  ######################################################################
  publish_release:
    needs: [build_windows, build_macos, build_linux, build_wheel, build_docker]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Download all artifacts
        uses: actions/download-artifact@v4
        with:
          path: release-assets/
          merge-multiple: true

      - name: Create GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          files: release-assets/*
          generate_release_notes: true
          fail_on_unmatched_files: false
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

---

## 5. .spec 文件（三个平台共用一份模板）

```python
# spec/kodeforge.spec  ← 放在仓库根目录的 spec/ 下
# 三个平台共用同一份（PyInstaller 会自动处理平台差异）

# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files

block_cipher = None

# 收集所有依赖的动态模块（核心！）
tools_datas, tools_binaries, tools_hiddenimports = collect_all('tools')
agents_datas, agents_binaries, agents_hiddenimports = collect_all('agents')

# 整合 config 目录
config_files = []
config_dir = Path('config')
if config_dir.exists():
    for f in config_dir.rglob('*'):
        if f.is_file():
            rel = f.parent.relative_to(config_dir)
            config_files.append((str(f), str(Path('config') / rel)))

a = Analysis(
    ['tools/cc_cli.py'],
    pathex=[],
    binaries=tools_binaries + agents_binaries,
    datas=[
        *tools_datas,
        *agents_datas,
        *config_files,
    ],
    hiddenimports=[
        *tools_hiddenimports,
        *agents_hiddenimports,
        'tools.rag.*',
        'tools.quality.*',
        'tools.hitl.*',
        'tools.compiler.*',
        'tools.workflow.*',
        'agents.supervisor',
        'agents.supervisor.*',
        'agents.experts',
        'agents.experts.*',
        'agents.runtime',
        'agents.runtime.*',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['spec/runtime_hook.py'],
    excludes=['matplotlib', 'tkinter', 'IPython'],  # 裁剪不需要的大包
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,      # onefile 模式需要打包二进制，--onedir 时为 []
    a.zipfiles,
    a.datas,
    [],
    name='kodeforge',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,       # Linux 可考虑 strip=True 减小体积
    upx=True,          # 使用 UPX 压缩（需要在 runner 上安装 upx）
    upx_exclude=[],
    runtime_tmpdir=None,   # 解压到临时目录，每次启动都重新解压（无状态）
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,  # macOS 上 ⌘+Q 等行为
    target_arch=None,      # 不指定 = 使用 runner 本地架构
    codesign_identity=None,
    entitlements_file=None,
)
```

```python
# spec/runtime_hook.py
# PyInstaller 自动调用，在 main script 之前执行
import sys
import os

# 让 __file__ 在 frozen 模式下也能正常工作
if getattr(sys, 'frozen', False):
    os.environ['KODEFORGE_FROZEN'] = '1'
    # 设置 HOME 兼容（Windows 上需要）
    if sys.platform == 'win32':
        os.environ.setdefault('USERPROFILE', os.path.expanduser('~'))
```

---

## 6. 本地验证脚本

```bash
# scripts/build_local.sh   （放在 scripts/ 下）
# 本地用 PyInstaller 构建后在本地测试

bash scripts/build_pyinstaller.sh --onedir
# 如果成功，输出 dist/pyinstaller/kodeforge/（目录模式）

# 验证
./dist/pyinstaller/kodeforge/kodeforge --version
./dist/pyinstaller/kodeforge/kodeforge validate
```

---

## 7. 产物大小预估

| 平台 | 模式 | 预估大小 | 说明 |
|------|------|---------|------|
| Windows | onefile | ~180 MB | UPX 压缩后 ~90 MB |
| Windows | onedir | ~120 MB | 启动更快，可以单独更新文件 |
| macOS | onefile | ~200 MB | 需要 codesign 才能不被 Gatekeeper 拦截 |
| macOS | onedir | ~140 MB | **推荐** macOS 用 onedir |
| Linux | onedire | ~110 MB | 体积最小，因为 runners 已有大部分 .so |

---

## 8. macOS Gatekeeper 问题（重要！）

macOS 用户下载 unsigned 二进制后会看到「已损坏，无法打开」的弹窗。

解决方案：
1. **推荐**：在 README 中写明：`xattr -cr kodeforge-vX.Y.Z-macos-x64.app` 运行一次即可
2. **长期**：购买 Apple Developer ID (\$99/年) + notarize 签名，PyInstaller 支持自动签名参数
3. **折中**：用 `hdiutil` 打包成 `.dmg`，dmg 签名比单文件签名更容易被接受

---

## 9. 在 CI 中安装 UPX（减小体积）

在 build job 的步骤里加一段：

```yaml
# Windows  runner（UPX 已预装）
# macOS  runner（需要手动安装）：
- name: Install UPX (macOS)
  if: runner.os == 'macOS'
  run: brew install upx

# Ubuntu（需要手动安装）：
- name: Install UPX (Linux)
  if: runner.os == 'Linux'
  run: sudo apt-get install -y upx-ucl
```

---

## 10. 发布流程（你操作）

```bash
git tag v0.5.0
git push origin v0.5.0
# → GitHub Actions 自动跑测试 + 构建所有平台产物 + Docker push
# → Release 自动生成并挂载所有产物（含 release notes）
# → 你可以在 GitHub Release 页面编辑 release notes，补充具体更新说明
```

---

## 11. 已经在仓库里有的东西

| 文件 | 状态 | 备注 |
|------|------|------|
| `.github/workflows/ci.yml` | 已有 | 测试阶段复用 |
| `.github/workflows/docker-release.yml` | 已有 | Docker push 阶段复用 |
| `.github/workflows/docker.yml` | 已有 | 保持不变 |
| `pyproject.toml` | 已有 | entry point 已配置 |
| `requirements.txt` | 已有 | 需要加 `pyinstaller` 到 `requirements-build.txt` |
