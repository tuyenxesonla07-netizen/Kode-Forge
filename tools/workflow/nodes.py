# tools/workflow/nodes.py

"""
工作流节点类型。

每种节点实现 `async execute(inputs: dict) -> output` 接口。
节点通过 `node_id` 标识，通过 `inputs` 定义上游依赖。

节点类型:
    LLMNode    — LLM 调用
    RAGNode    — 知识库检索
    ToolNode   — MCP 工具调用
    CodeNode   — Python 代码执行
    BranchNode — 条件分支
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List
from enum import Enum

logger = logging.getLogger(__name__)


class NodeType(str, Enum):
    LLM = "llm"
    RAG = "rag"
    TOOL = "tool"
    CODE = "code"
    BRANCH = "branch"
    HUMAN = "human"


@dataclass
class WorkflowNode:
    """工作流节点定义"""
    id: str
    type: NodeType
    name: str = ""
    config: Dict[str, Any] = field(default_factory=dict)
    inputs: List[str] = field(default_factory=list)  # 上游节点 id 列表
    version: str = "1.0.0"                           # 节点版本
    permissions: List[str] = field(default_factory=list)  # 所需权限标签
    side_effect: bool = False                         # 是否有副作用
    idempotent: bool = False                          # 是否幂等


class LLMNode:
    """LLM 调用节点"""

    def __init__(self, prompt_template: str = "", provider=None,
                 model: str = "", temperature: float = 0.7, max_tokens: int = 4096):
        self.prompt_template = prompt_template
        self.provider = provider
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    async def execute(self, inputs: dict) -> str:
        prompt = self.prompt_template
        # 替换 {{input}} 占位符
        for key, value in inputs.items():
            prompt = prompt.replace(f"{{{{{key}}}}}", str(value))

        if not self.provider:
            return f"[LLMNode] {prompt}"

        # 优先使用 acomplete（异步），回退到 complete（同步）
        if hasattr(self.provider, 'acomplete'):
            response = await self.provider.acomplete(
                prompt=prompt,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
        else:
            response = self.provider.complete(
                prompt=prompt,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
        return response.content if response.success else f"Error: {response.error}"


class RAGNode:
    """知识库检索节点"""

    def __init__(self, rag_engine=None, top_k: int = 5):
        self.rag_engine = rag_engine
        self.top_k = top_k

    async def execute(self, inputs: dict) -> dict:
        query = inputs.get("query", "")
        if not self.rag_engine or not query:
            return {"sources": [], "query": query}

        result = await self.rag_engine.query(query, top_k=self.top_k,
                                             provider=getattr(self, "provider", None))
        return {
            "answer": result.answer,
            "sources": [s.content[:200] for s in result.sources],
            "query": query,
        }


class ToolNode:
    """MCP 工具调用节点"""

    def __init__(self, tool_registry=None, tool_name: str = "",
                 arguments: dict = None):
        self.tool_registry = tool_registry
        self.tool_name = tool_name
        self.arguments = arguments or {}

    async def execute(self, inputs: dict) -> dict:
        if not self.tool_registry or not self.tool_name:
            return {"error": "Tool not configured"}

        # 合并 inputs 到 arguments
        args = {**self.arguments}
        for key, value in inputs.items():
            if key not in args:
                args[key] = value

        try:
            result = await self.tool_registry.call(self.tool_name, args)
            return {"result": result, "tool": self.tool_name}
        except Exception as e:
            return {"error": str(e), "tool": self.tool_name}


class CodeNode:
    """Python 代码执行节点（沙箱模式）"""

    def __init__(self, code_template: str = "", safe_mode: bool = False):
        self.code_template = code_template
        self.safe_mode = safe_mode

    async def execute(self, inputs: dict) -> dict:
        code = self.code_template
        for key, value in inputs.items():
            code = code.replace(f"{{{{{key}}}}}", repr(value))

        # 安全模式：AST 检查危险导入
        if self.safe_mode:
            from tools.quality.ast_validator import ASTValidator
            validator = ASTValidator()
            issues = validator.validate_dangerous_imports(code)
            if issues:
                return {
                    "error": f"Code safety check failed: {issues[0].message}",
                    "safety_issues": [i.message for i in issues],
                }

        try:
            # 安全沙箱：只允许基本运算
            allowed_builtins = {
                "len": len, "str": str, "int": int, "float": float,
                "list": list, "dict": dict, "print": print,
                "range": range, "enumerate": enumerate, "zip": zip,
            }
            local_vars = {}
            exec(code, {"__builtins__": allowed_builtins}, local_vars)
            return {"output": str(local_vars.get("result", local_vars))}
        except Exception as e:
            return {"error": f"Code execution failed: {e}"}


class BranchNode:
    """条件分支节点"""

    def __init__(self, condition: str = "true",
                 branches: Dict[str, str] = None):
        """
        Args:
            condition: 条件表达式（基于 inputs）
            branches: {分支名: 目标节点 id}
        """
        self.condition = condition
        self.branches = branches or {"true": "", "false": ""}

    async def execute(self, inputs: dict) -> str:
        try:
            result = eval(self.condition, {"__builtins__": {}}, inputs)
            branch = "true" if result else "false"
            target = self.branches.get(branch, "")
            return {"branch": branch, "target": target}
        except Exception:
            return {"branch": "false", "target": self.branches.get("false", "")}


class HumanNode:
    """
    人工审批节点 — 暂停执行等待人类确认。

    参考 customer-service-agent 的 6 步执行管道第 4 步 (approval)。
    当工作流执行到此节点时，会触发 HITL 审批流程：
      1. 创建审批请求（包含操作描述和风险等级）
      2. 等待人类通过 callback() 确认或拒绝
      3. 根据审批结果继续或中止工作流

    用法:
        node = HumanNode(
            prompt="确认删除用户数据？",
            risk_level="high",
            approval_handler=AutoApprovalHandler(),
        )
        result = await node.execute({"user_id": "U123"})
        # result = {"approved": True/False, "approver": "auto"/"human_xxx"}
    """

    def __init__(self, prompt: str = "需要人工确认",
                 risk_level: str = "high",
                 approval_handler=None):
        self.prompt = prompt
        self.risk_level = risk_level
        self.approval_handler = approval_handler

    async def execute(self, inputs: dict) -> dict:
        if not self.approval_handler:
            # 无审批处理器时自动通过（降级模式）
            return {"approved": True, "approver": "none", "prompt": self.prompt}

        request_args = {**inputs, "_prompt": self.prompt}
        result = self.approval_handler.request_approval(
            tool_name=f"human_node_{self.prompt[:20]}",
            args=request_args,
            risk_level=self.risk_level,
            context=inputs,
        )

        return {
            "approved": result.approved,
            "approver": result.approver,
            "comment": result.comment,
            "requires_human": result.requires_human,
            "prompt": self.prompt,
        }
