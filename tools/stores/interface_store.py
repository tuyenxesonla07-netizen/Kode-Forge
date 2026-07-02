"""
tools/stores/interface_store.py

接口定义存储 — 按模块存储其对外暴露的接口
填充时机: 专家 Agent 产出 ModuleSpec 后
读取时机: ContextInjector 为依赖模块注入接口时
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class InterfaceDef:
    """单个接口定义（不含实现）"""
    name: str                        # 接口名称，如 "login"
    method: str                      # HTTP 方法
    path: str                        # 路径
    input_schema: Dict = field(default_factory=dict)   # 输入 Schema
    output_schema: Dict = field(default_factory=dict)  # 输出 Schema
    description: str = ""            # 接口描述
    module: str = ""                 # 所属模块


class InterfaceStore:
    """接口定义存储"""

    def __init__(self) -> None:
        # 结构: { module_name: { interface_name: InterfaceDef } }
        self._store: Dict[str, Dict[str, InterfaceDef]] = {}

    def register_module(self, module: str, interfaces: List[InterfaceDef]) -> None:
        """注册一个模块的所有接口"""
        for iface in interfaces:
            iface.module = module
        self._store[module] = {iface.name: iface for iface in interfaces}

    def register_interface(self, module: str, interface: InterfaceDef) -> None:
        """注册单个接口"""
        interface.module = module
        if module not in self._store:
            self._store[module] = {}
        self._store[module][interface.name] = interface

    def get_for_injection(self, module: str) -> str:
        """
        返回该模块的所有接口定义，用于注入依赖模块
        这是最小权限的核心：依赖方只看到接口签名，看不到实现
        返回格式化的字符串，可直接注入 Agent 上下文
        """
        return self.get_interface_summary(module)

    def get_interface(self, module: str, name: str) -> Optional[InterfaceDef]:
        """获取特定接口"""
        return self._store.get(module, {}).get(name)

    def get_interface_summary(self, module: str) -> str:
        """
        返回格式化的接口摘要，直接注入 Agent 上下文
        只包含接口签名，不包含实现代码
        """
        interfaces = self._store.get(module, {})
        if not interfaces:
            return ""

        lines = [f"## {module} 接口定义（仅签名）", ""]
        for name, iface in interfaces.items():
            lines.append(f"- **{iface.name}** `{iface.method} {iface.path}`")
            if iface.description:
                lines.append(f"  - 描述: {iface.description}")
            if iface.input_schema:
                lines.append(f"  - 输入: {iface.input_schema}")
            if iface.output_schema:
                lines.append(f"  - 输出: {iface.output_schema}")
            lines.append("")

        return "\n".join(lines)

    def get_all_modules(self) -> List[str]:
        """获取所有已注册接口的模块名"""
        return list(self._store.keys())

    def get_cross_module_interfaces(self, module_names: List[str]) -> Dict[str, Dict[str, InterfaceDef]]:
        """获取多个模块的接口（用于跨模块契约对齐）"""
        result = {}
        for name in module_names:
            if name in self._store:
                result[name] = self._store[name]
        return result

    def clear(self) -> None:
        """清空存储"""
        self._store.clear()

    def __len__(self) -> int:
        return sum(len(ifaces) for ifaces in self._store.values())
