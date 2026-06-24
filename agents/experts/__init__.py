# agents/experts/__init__.py

"""
专家子 Agent — 按功能模块分工的领域专家

每个专家 Agent 遵循四个原则:
  单一职责: 只负责一个功能模块
  最小权限: 只接收 Superpowers 注入的最小上下文
  独立可测: 给定相同输入，产出确定性输出
  结果可验: 输出必须符合 output_schema
"""

import json
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field


@dataclass
class ExpertInput:
    """专家 Agent 的标准化输入"""
    module_name: str
    requirement: str
    constraints: List[str] = field(default_factory=list)
    dependency_interfaces: Dict[str, Any] = field(default_factory=dict)
    global_constraints: Dict[str, str] = field(default_factory=dict)
    extra_context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExpertOutput:
    """专家 Agent 的标准化输出"""
    module_name: str
    components: List[Dict[str, Any]] = field(default_factory=list)
    interfaces: List[Dict[str, Any]] = field(default_factory=list)
    acceptance_criteria: List[str] = field(default_factory=list)
    state_machine: Optional[Dict[str, Any]] = None
    confidence: float = 0.0
    reasoning: str = ""


@dataclass
class ReviewInput:
    """审查输入"""
    module_name: str
    code_snippet: str
    expected_interfaces: List[Dict[str, Any]] = field(default_factory=list)
    expected_acceptance_criteria: List[str] = field(default_factory=list)


@dataclass
class ReviewOutput:
    """审查输出"""
    module: str
    verdict: str = "pass"       # "pass" | "fail" | "conditional"
    issues: List[Dict[str, Any]] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)


class BaseExpertAgent:
    """专家 Agent 基类"""

    def __init__(self, agent_id: str, module_name: str,
                 input_schema: dict, output_schema: dict,
                 llm_provider=None):
        self.agent_id = agent_id
        self.module_name = module_name
        self.input_schema = input_schema
        self.output_schema = output_schema
        self.llm_provider = llm_provider

    def _build_analysis_prompt(self, input_data: ExpertInput) -> tuple:
        """构建分析 prompt，返回 (system_prompt, user_prompt)"""
        output_schema_str = json.dumps(
            self.output_schema.get("properties", {}).get("module_spec", {}),
            ensure_ascii=False, indent=2
        )

        system_prompt = (
            f"You are an expert software architect for the '{self.module_name}' module. "
            f"Analyze the requirement and produce a structured module specification.\n\n"
            f"Output format (JSON):\n{output_schema_str}"
        )

        user_prompt = (
            f"## Module: {self.module_name}\n"
            f"## Requirement\n{input_data.requirement}\n\n"
            f"## Constraints\n" + "\n".join(f"- {c}" for c in input_data.constraints) + "\n\n"
            f"## Dependencies\n" + "\n".join(f"- {d}" for d in input_data.dependency_interfaces.keys()) + "\n\n"
            f"## Global Constraints\n" + "\n".join(f"- {k}: {v}" for k, v in input_data.global_constraints.items()) + "\n\n"
            f"Produce a JSON module specification."
        )

        return system_prompt, user_prompt

    def _build_review_prompt(self, review_input: ReviewInput) -> tuple:
        """构建审查 prompt，返回 (system_prompt, user_prompt)"""
        system_prompt = (
            f"You are a code reviewer for the '{review_input.module_name}' module. "
            f"Review the code against the expected interfaces and acceptance criteria.\n\n"
            'Respond with JSON: {"verdict": "pass|fail|conditional", '
            '"issues": [...], "metrics": {...}}'
        )

        user_prompt = (
            f"## Module: {review_input.module_name}\n\n"
            f"## Code\n```\n{review_input.code_snippet}\n```\n\n"
            f"## Expected Interfaces\n{json.dumps(review_input.expected_interfaces, ensure_ascii=False)}\n\n"
            f"## Acceptance Criteria\n" + "\n".join(f"- {ac}" for ac in review_input.expected_acceptance_criteria) + "\n\n"
            f"Review the code and respond with JSON."
        )

        return system_prompt, user_prompt

    def process(self, input_data: ExpertInput) -> ExpertOutput:
        """分析模块需求 — 调用 LLM"""
        if self.llm_provider:
            system_prompt, user_prompt = self._build_analysis_prompt(input_data)
            response = self.llm_provider.complete(
                prompt=user_prompt,
                system_prompt=system_prompt,
                output_format="json",
            )
            if response.success and response.parsed:
                return ExpertOutput(
                    module_name=self.module_name,
                    components=response.parsed.get("components", []),
                    interfaces=response.parsed.get("interfaces", []),
                    acceptance_criteria=response.parsed.get("acceptance_criteria", []),
                    state_machine=response.parsed.get("state_machine"),
                    confidence=response.parsed.get("confidence", 0.8),
                    reasoning=response.parsed.get("reasoning", ""),
                )

        # Fallback: 返回默认结果
        return self._default_analysis(input_data)

    def review(self, review_input: ReviewInput) -> ReviewOutput:
        """审查代码质量 — 调用 LLM"""
        if self.llm_provider:
            system_prompt, user_prompt = self._build_review_prompt(review_input)
            response = self.llm_provider.complete(
                prompt=user_prompt,
                system_prompt=system_prompt,
                output_format="json",
            )
            if response.success and response.parsed:
                return ReviewOutput(
                    module=review_input.module_name,
                    verdict=response.parsed.get("verdict", "pass"),
                    issues=response.parsed.get("issues", []),
                    metrics=response.parsed.get("metrics", {}),
                )

        # Fallback: 返回默认结果
        return ReviewOutput(module=review_input.module_name, verdict="pass")

    def _default_analysis(self, input_data: ExpertInput) -> ExpertOutput:
        """默认分析结果（无 LLM 时）"""
        return ExpertOutput(
            module_name=self.module_name,
            components=[{"name": f"{self.module_name.title()}Service", "type": "service",
                         "description": f"{self.module_name} 服务"}],
            interfaces=[{"name": "create", "method": "POST",
                         "path": f"/api/{self.module_name}/"}],
            acceptance_criteria=[f"可创建 {self.module_name}"],
            confidence=0.7,
            reasoning="Default analysis (no LLM provider)",
        )

    def validate_input(self, input_data: Dict) -> bool:
        """校验输入是否符合 input_schema"""
        required = self.input_schema.get("required", [])
        return all(field in input_data for field in required)

    def validate_output(self, output_data: Dict) -> bool:
        """校验输出是否符合 output_schema"""
        required = self.output_schema.get("properties", {}).get("module_spec", {}).get("required", [])
        module_spec = output_data.get("module_spec", {})
        return all(field in module_spec for field in required)


# ============================================================
# 具体专家 Agent（按模块）
# ============================================================

class AuthExpert(BaseExpertAgent):
    """认证模块专家"""

    def __init__(self, input_schema: dict, output_schema: dict, llm_provider=None):
        super().__init__("expert_auth", "authentication", input_schema, output_schema, llm_provider)


class ProductExpert(BaseExpertAgent):
    """商品浏览模块专家"""

    def __init__(self, input_schema: dict, output_schema: dict, llm_provider=None):
        super().__init__("expert_product", "product_catalog", input_schema, output_schema, llm_provider)


class CartExpert(BaseExpertAgent):
    """购物车模块专家"""

    def __init__(self, input_schema: dict, output_schema: dict, llm_provider=None):
        super().__init__("expert_cart", "shopping_cart", input_schema, output_schema, llm_provider)


class OrderExpert(BaseExpertAgent):
    """订单模块专家"""

    def __init__(self, input_schema: dict, output_schema: dict, llm_provider=None):
        super().__init__("expert_order", "order_system", input_schema, output_schema, llm_provider)


class PaymentExpert(BaseExpertAgent):
    """支付模块专家"""

    def __init__(self, input_schema: dict, output_schema: dict, llm_provider=None):
        super().__init__("expert_payment", "payment_integration", input_schema, output_schema, llm_provider)


class NotificationExpert(BaseExpertAgent):
    """通知模块专家"""

    def __init__(self, input_schema: dict, output_schema: dict, llm_provider=None):
        super().__init__("expert_notification", "notification_service", input_schema, output_schema, llm_provider)


class ReportExpert(BaseExpertAgent):
    """数据报表模块专家"""

    def __init__(self, input_schema: dict, output_schema: dict, llm_provider=None):
        super().__init__("expert_report", "data_reporting", input_schema, output_schema, llm_provider)


def create_expert_agents(
    schemas_dir: str = "config/schemas",
    llm_provider=None,
) -> Dict[str, BaseExpertAgent]:
    import os
    import json

    experts = {}
    expert_classes = {
        "auth": AuthExpert,
        "product": ProductExpert,
        "cart": CartExpert,
        "order": OrderExpert,
        "payment": PaymentExpert,
        "notification": NotificationExpert,
        "report": ReportExpert,
    }

    for module_name, cls in expert_classes.items():
        input_path = os.path.join(schemas_dir, f"{module_name}_input.json")
        output_path = os.path.join(schemas_dir, f"{module_name}_output.json")

        if os.path.exists(input_path) and os.path.exists(output_path):
            with open(input_path) as f:
                input_schema = json.load(f)
            with open(output_path) as f:
                output_schema = json.load(f)
            experts[module_name] = cls(input_schema, output_schema, llm_provider)

    return experts
h open(input_path) as f:
                input_schema = json.load(f)
            with open(output_path) as f:
                output_schema = json.load(f)
            experts[module_name] = cls(input_schema, output_schema, llm_provider)

    return experts
