# tools/stores/__init__.py

"""
Store 组件 — 三大逻辑存储

  RequirementStore  — 需求上下文存储（Codex 写入，ContextInjector 读取）
  InterfaceStore    — 接口定义存储（Expert Agent 写入，ContextInjector 读取）
  SpecStore         — 模块规格存储（Expert Agent 写入，Prompt Agent 读取）
"""

from tools.stores.requirement_store import RequirementStore, ModuleRequirement
from tools.stores.interface_store import InterfaceStore, InterfaceDef
from tools.stores.spec_store import SpecStore, ModuleSpec
from tools.stores.persistence import StoreDatabase

# Optional PostgreSQL store
try:
    _POSTGRES_AVAILABLE = True
except ImportError:
    _POSTGRES_AVAILABLE = False

__all__ = [
    "RequirementStore",
    "ModuleRequirement",
    "InterfaceStore",
    "InterfaceDef",
    "SpecStore",
    "ModuleSpec",
    "StoreDatabase",
]

if _POSTGRES_AVAILABLE:
    __all__.extend(["AsyncPostgresStore", "DocumentChunk"])
