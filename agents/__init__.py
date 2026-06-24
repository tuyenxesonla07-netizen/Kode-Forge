# agents/__init__.py

"""
Agent 层 — 主管 + 专家子 Agent

agents/supervisor/  → Codex 主管 Agent
agents/experts/     → 专家子 Agent（按功能模块）
"""

from typing import Protocol, Dict, Any, Optional


class AgentProtocol(Protocol):
    """Agent 协议定义"""
    agent_id: str
    module_name: str

    def process(self, input_data: Dict) -> Dict:
        """处理输入，返回输出"""
        ...

    def validate_input(self, input_data: Dict) -> bool:
        """校验输入是否符合 input_schema"""
        ...

    def validate_output(self, output_data: Dict) -> bool:
        """校验输出是否符合 output_schema"""
        ...
