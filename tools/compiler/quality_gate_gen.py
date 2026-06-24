"""
tools/compiler/quality_gate_gen.py

质量门禁生成器 — 从模块 Schema 自动推导质量门禁配置

核心创新：不是人工定义统一的质量门禁，而是根据各模块的 Schema 特征生成针对性的门禁。
认证模块的安全门禁更严格，报表模块的数据准确性门禁更严格。
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class QualityGate:
    """单个质量门禁规则"""
    name: str
    metric: str
    operator: str          # ">=", "==", ">", "<", "in"
    threshold: Any
    blocking: bool         # 是否阻塞流水线
    description: str
    applies_to: List[str]  # 适用的模块列表（空 = 所有模块）


@dataclass
class QualityGateSuite:
    """完整的质量门禁套件"""
    gates: List[QualityGate] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def evaluate(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """评估质量门禁"""
        results = {
            "passed": True,
            "gate_results": [],
            "failed_gates": [],
        }

        for gate in self.gates:
            actual_value = metrics.get(gate.metric)
            if actual_value is None:
                continue

            passed = self._check_threshold(actual_value, gate.operator, gate.threshold)
            result = {
                "gate": gate.name,
                "metric": gate.metric,
                "expected": f"{gate.operator} {gate.threshold}",
                "actual": actual_value,
                "passed": passed,
                "blocking": gate.blocking,
            }
            results["gate_results"].append(result)

            if not passed:
                if gate.blocking:
                    results["passed"] = False
                results["failed_gates"].append(result)

        return results

    def _check_threshold(self, actual: Any, operator: str, threshold: Any) -> bool:
        """检查阈值"""
        if operator == ">=":
            return actual >= threshold
        elif operator == "==":
            return actual == threshold
        elif operator == ">":
            return actual > threshold
        elif operator == "<":
            return actual < threshold
        elif operator == "<=":
            return actual <= threshold
        elif operator == "in":
            return actual in threshold
        return False


class QualityGateGenerator:
    """从模块 Schema 自动生成质量门禁配置"""

    def generate(self, module_schemas: Dict[str, dict],
                 global_config: Optional[Dict] = None) -> QualityGateSuite:
        """
        生成逻辑:
          1. 所有模块共享的基础门禁（编译通过、无 critical 问题）
          2. 根据 Schema 特征生成针对性门禁
          3. 根据模块依赖关系调整门禁严格程度
        """
        suite = QualityGateSuite()
        global_config = global_config or {}

        # === 基础门禁（所有模块） ===
        suite.gates.append(QualityGate(
            name="all_modules_pass_review",
            metric="all_modules_passed",
            operator="==",
            threshold=True,
            blocking=True,
            description="所有模块审查通过",
            applies_to=[],
        ))

        suite.gates.append(QualityGate(
            name="no_critical_issues",
            metric="critical_issues_count",
            operator="==",
            threshold=0,
            blocking=True,
            description="无严重级别问题",
            applies_to=[],
        ))

        suite.gates.append(QualityGate(
            name="interface_consistency",
            metric="interface_consistency",
            operator="==",
            threshold=True,
            blocking=True,
            description="跨模块接口一致",
            applies_to=[],
        ))

        # === 根据 Schema 特征生成针对性门禁 ===
        for module_name, schema in module_schemas.items():
            spec_props = schema.get("properties", {}).get("module_spec", {})

            # 有 acceptance_criteria 的模块 → 验收标准检查
            if "acceptance_criteria" in spec_props.get("required", []):
                suite.gates.append(QualityGate(
                    name=f"{module_name}_acceptance_met",
                    metric=f"{module_name}_acceptance_met",
                    operator="==",
                    threshold=True,
                    blocking=True,
                    description=f"{module_name} 验收标准全部满足",
                    applies_to=[module_name],
                ))

            # 有 state_machine 的模块 → 状态机完整性检查
            if "state_machine" in spec_props.get("properties", {}):
                suite.gates.append(QualityGate(
                    name=f"{module_name}_state_machine_complete",
                    metric=f"{module_name}_state_machine_complete",
                    operator="==",
                    threshold=True,
                    blocking=True,
                    description=f"{module_name} 状态机定义完整",
                    applies_to=[module_name],
                ))

            # 有 security_requirements 的模块 → 安全评分检查
            input_props = module_schemas.get(module_name, {}).get("properties", {})
            if "security_requirements" in input_props or module_name in ["authentication", "payment"]:
                suite.gates.append(QualityGate(
                    name=f"{module_name}_security_score",
                    metric="security_score",
                    operator=">=",
                    threshold=0.9,
                    blocking=True,
                    description=f"{module_name} 安全评分 >= 0.9",
                    applies_to=[module_name],
                ))

            # 有 compliance_requirements 的模块 → 合规检查
            if "compliance_requirements" in input_props:
                suite.gates.append(QualityGate(
                    name=f"{module_name}_compliance_check",
                    metric=f"{module_name}_compliant",
                    operator="==",
                    threshold=True,
                    blocking=True,
                    description=f"{module_name} 合规检查通过",
                    applies_to=[module_name],
                ))

        # === 通用质量门禁 ===
        suite.gates.append(QualityGate(
            name="test_coverage",
            metric="test_coverage",
            operator=">=",
            threshold=global_config.get("min_test_coverage", 0.7),
            blocking=False,
            description="测试覆盖率达标",
            applies_to=[],
        ))

        suite.gates.append(QualityGate(
            name="quality_score",
            metric="quality_score",
            operator=">=",
            threshold=global_config.get("min_quality_score", 0.8),
            blocking=True,
            description="综合质量评分达标",
            applies_to=[],
        ))

        suite.metadata = {
            "total_gates": len(suite.gates),
            "blocking_gates": sum(1 for g in suite.gates if g.blocking),
            "modules_with_custom_gates": list(module_schemas.keys()),
        }

        return suite
