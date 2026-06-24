"""
tools/stores/spec_store.py

模块规格存储 — 存储专家产出的完整 ModuleSpec
填充时机: 专家 Agent 产出后
读取时机: Prompt Agent 整合时
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class ComponentDef:
    """组件定义"""
    name: str
    type: str         # service / model / route / middleware / util / template
    description: str
    methods: List[str] = field(default_factory=list)


@dataclass
class StateMachineDef:
    """状态机定义"""
    states: List[str] = field(default_factory=list)
    transitions: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class ModuleSpec:
    """单个模块的完整规格"""
    module_name: str
    components: List[ComponentDef] = field(default_factory=list)
    interfaces: List[Any] = field(default_factory=list)  # List[InterfaceDef]
    acceptance_criteria: List[str] = field(default_factory=list)
    state_machine: Optional[StateMachineDef] = None
    confidence: float = 0.0
    reasoning: str = ""


class SpecStore:
    """模块规格存储"""

    def __init__(self):
        self._store: Dict[str, ModuleSpec] = {}

    def put(self, module: str, spec: ModuleSpec) -> None:
        """存储模块规格"""
        self._store[module] = spec

    def get(self, module: str) -> Optional[ModuleSpec]:
        """获取模块规格"""
        return self._store.get(module)

    def get_all(self) -> Dict[str, ModuleSpec]:
        """获取所有规格"""
        return dict(self._store)

    def get_ordered(self, module_order: List[str]) -> List[ModuleSpec]:
        """按实现顺序返回所有 Spec"""
        return [self._store[m] for m in module_order if m in self._store]

    def get_all_acceptance_criteria(self) -> Dict[str, List[str]]:
        """获取所有模块的验收标准（用于质量门禁）"""
        return {
            name: spec.acceptance_criteria
            for name, spec in self._store.items()
        }

    def get_overall_confidence(self) -> float:
        """计算所有模块的平均置信度"""
        if not self._store:
            return 0.0
        return sum(s.confidence for s in self._store.values()) / len(self._store)

    def get_modules_with_state_machine(self) -> List[str]:
        """获取有状态机的模块列表"""
        return [name for name, spec in self._store.items() if spec.state_machine is not None]

    def clear(self):
        """清空存储"""
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)
