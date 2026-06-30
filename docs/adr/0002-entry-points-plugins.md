# ADR-0002: Entry Points 插件发现机制

## 状态
Accepted (V0.4.0 F2)

## 背景

`tools/llm/__init__.py` 中的 `create_llm_provider()` 函数最初通过硬编码字典 `_OPENAI_COMPATIBLE_BACKENDS` 支持 20+ 后端。每次新增后端都需要修改该字典，且第三方无法扩展。

## 决策

采用 Python 标准 `importlib.metadata.entry_points()` 实现插件发现：

```toml
# pyproject.toml
[project.entry-points."cc.plugins.providers"]
anthropic = "tools.llm.anthropic:AnthropicClaudeProvider"
openai_compatible = "tools.llm.providers:OpenAICompatibleProvider"
gemini = "tools.llm.providers:GeminiProvider"
```

### PluginLoader 接口

```python
class PluginLoader:
    ENTRY_POINT_GROUP = "cc.plugins.providers"

    def discover() -> dict[str, PluginMetadata]: ...
    def load(name: str, **kwargs) -> LLMProvider: ...
    def list_available() -> list[PluginMetadata]: ...
```

### 内置 vs 第三方

- **内置 provider**：通过 `pyproject.toml` 的 `[project.entry-points]` 声明，随包安装自动注册
- **第三方 provider**：通过独立 pip 包，在 `setup.py`/`pyproject.toml` 中声明 `cc.plugins.providers` entry point
- **发现时机**：`create_llm_provider()` 首次调用时懒加载，缓存结果

## 后果

**优点**：
- 零运行时依赖（`importlib.metadata` 是 Python 3.12 标准库）
- 第三方包无需修改本项目代码即可注册新 provider
- 向后兼容：旧字典作为 fallback，未安装 entry_points 时仍可用

**缺点**：
- 调试时插件不显示在 traceback 中（entry point 加载是黑盒）
- 需要确保 `pyproject.toml` 的 entry_points 与代码同步

## 相关

- ADR-0006: 多渠道消息适配器的 Lazy Import 模式
- `tools/llm/plugin.py` — PluginLoader 实现
- `tools/llm/plugin_config.py` — CopilotPluginManifest 解析
