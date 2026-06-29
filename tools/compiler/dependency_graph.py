"""
tools/compiler/dependency_graph.py

依赖图构建器 — 从 agents.yaml 的 dependencies 字段构建模块依赖图，
支持拓扑排序和环检测。
"""

from dataclasses import dataclass, field
from typing import List, Dict, Set, Tuple
from collections import deque

from tools.exceptions import DependencyCycleError


@dataclass
class DependencyGraph:
    """模块依赖图"""
    # 邻接表: module -> [依赖的模块列表]
    adjacency: Dict[str, List[str]] = field(default_factory=dict)
    # 所有模块节点
    nodes: Set[str] = field(default_factory=set)

    def add_module(self, module: str, dependencies: List[str] = None):
        """添加模块及其依赖"""
        self.nodes.add(module)
        if dependencies:
            self.adjacency[module] = list(dependencies)
            for dep in dependencies:
                self.nodes.add(dep)
        else:
            self.adjacency[module] = []

    def topological_sort(self) -> List[str]:
        """
        拓扑排序（Kahn's Algorithm）
        返回: 按依赖关系排序的模块列表（被依赖的在前）
        异常: 如果存在循环依赖，抛出 ValueError
        """
        # 计算入度：入度 = 该模块依赖的其他模块数量
        in_degree = {node: len(self.adjacency.get(node, [])) for node in self.nodes}

        # Kahn's algorithm
        queue = deque(sorted(n for n in self.nodes if in_degree[n] == 0))
        result = []

        while queue:
            node = queue.popleft()
            result.append(node)

            # 移除该节点的出边，更新依赖方的入度
            for module, deps in self.adjacency.items():
                if node in deps:
                    in_degree[module] -= 1
                    if in_degree[module] == 0:
                        queue.append(module)

        if len(result) != len(self.nodes):
            cycle_nodes = sorted(self.nodes - set(result))
            raise DependencyCycleError(cycle_nodes)

        return result

    def get_dependencies(self, module: str) -> List[str]:
        """获取模块的直接依赖"""
        return self.adjacency.get(module, [])

    def get_all_dependencies(self, module: str) -> Set[str]:
        """获取模块的所有传递依赖"""
        visited = set()
        stack = list(self.adjacency.get(module, []))

        while stack:
            dep = stack.pop()
            if dep not in visited:
                visited.add(dep)
                stack.extend(self.adjacency.get(dep, []))

        return visited

    def get_dependents(self, module: str) -> List[str]:
        """获取依赖该模块的所有模块（反向依赖）"""
        dependents = []
        for m, deps in self.adjacency.items():
            if module in deps:
                dependents.append(m)
        return dependents

    def has_cycle(self) -> bool:
        """检测是否存在循环依赖"""
        try:
            self.topological_sort()
            return False
        except DependencyCycleError:
            return True

    def get_parallel_groups(self) -> List[List[str]]:
        """
        获取可并行执行的模块组
        同一组的模块之间没有依赖关系，可以并行处理
        """
        in_degree = {node: 0 for node in self.nodes}
        for module in self.nodes:
            in_degree[module] = len(self.adjacency.get(module, []))

        groups = []
        remaining = set(self.nodes)

        while remaining:
            # 找出入度为 0 的剩余节点
            group = [n for n in remaining if in_degree[n] == 0]
            if not group:
                remaining_sorted = sorted(remaining)
                raise DependencyCycleError(remaining_sorted)

            groups.append(group)

            # 移除这些节点，更新入度
            for node in group:
                remaining.remove(node)
                for module in remaining:
                    if node in self.adjacency.get(module, []):
                        in_degree[module] -= 1

        return groups


class DependencyGraphBuilder:
    """从 agents.yaml 配置构建依赖图"""

    def __init__(self, agents_config: dict):
        """
        agents_config 结构:
        {
          "agents": {
            "expert_auth": { "dependencies": [] },
            "expert_order": { "dependencies": ["authentication"] },
            ...
          }
        }
        """
        self.agents_config = agents_config

    def build(self) -> DependencyGraph:
        """构建依赖图"""
        graph = DependencyGraph()
        agents = self.agents_config.get("agents", {})

        for agent_id, agent_config in agents.items():
            if agent_config.get("role") != "expert":
                continue

            module = agent_config.get("module", agent_id.replace("expert_", ""))
            deps = agent_config.get("dependencies", [])

            # 将模块名映射（如 "authentication" → 实际模块名）
            graph.add_module(module, deps)

        return graph

    def validate(self) -> Tuple[bool, List[str]]:
        """验证依赖图的一致性"""
        errors = []

        graph = self.build()

        # 检查循环依赖
        if graph.has_cycle():
            errors.append("存在循环依赖")

        # 检查所有依赖的模块是否存在
        agents = self.agents_config.get("agents", {})
        known_modules = {
            cfg.get("module", agent_id.replace("expert_", ""))
            for agent_id, cfg in agents.items()
            if cfg.get("role") == "expert"
        }

        for module in graph.nodes:
            for dep in graph.get_dependencies(module):
                if dep not in known_modules:
                    errors.append(f"模块 '{module}' 依赖不存在的模块 '{dep}'")

        return len(errors) == 0, errors
