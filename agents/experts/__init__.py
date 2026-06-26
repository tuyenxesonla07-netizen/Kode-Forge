# agents/experts/__init__.py

"""
专家子 Agent — 按功能模块分工的领域专家。

每个专家 Agent 遵循四个原则:
  单一职责: 只负责一个功能模块
  最小权限: 只接收 Superpowers 注入的最小上下文
  独立可测: 给定相同输入，产出确定性输出
  结果可验: 输出必须符合 output_schema

动态发现机制:
  1. 扫描 config/schemas/ 目录，自动发现所有模块（*_input.json / *_output.json）
  2. 从 agents.yaml 读取每个模块的能力声明（capabilities）
  3. 无需为每个模块编写独立 Python 类 — 一个通用 ExpertAgent 类即可

添加新模块:
  1. 在 config/schemas/ 添加 xxx_input.json + xxx_output.json
  2. 在 agents.yaml 添加 expert_xxx 配置（capabilities 等）
  3. 零 Python 代码改动
"""

import json
import os
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


class ExpertAgent:
    """
    通用专家 Agent — 所有模块共用一个类。

    模块差异化完全由配置驱动：
    - input_schema / output_schema: 从 config/schemas/ 加载
    - capabilities: 从 agents.yaml 读取
    - review_capabilities: 从 agents.yaml 读取

    用法:
        agent = ExpertAgent(
            agent_id="expert_auth",
            module_name="authentication",
            capabilities=["jwt_auth", "oauth2"],
            input_schema={...},
            output_schema={...},
            llm_provider=provider,
        )
        output = agent.process(input_data)
    """

    def __init__(
        self,
        agent_id: str,
        module_name: str,
        input_schema: dict,
        output_schema: dict,
        llm_provider=None,
        capabilities: List[str] = None,
        review_capabilities: List[str] = None,
        version: str = "1.0.0",
        skill_manager=None,
    ):
        self.agent_id = agent_id
        self.module_name = module_name
        self.input_schema = input_schema
        self.output_schema = output_schema
        self.llm_provider = llm_provider
        self.capabilities = capabilities or []
        self.review_capabilities = review_capabilities or []
        self.version = version
        self.skill_manager = skill_manager

    def _build_analysis_prompt(self, input_data: ExpertInput) -> tuple:
        """构建分析 prompt，返回 (system_prompt, user_prompt)"""
        output_schema_str = json.dumps(
            self.output_schema.get("properties", {}).get("module_spec", {}),
            ensure_ascii=False, indent=2,
        )
        capabilities_str = ", ".join(self.capabilities) if self.capabilities else "general"

        # Inject relevant skills into system prompt
        skill_section = ""
        if self.skill_manager:
            skills = self.skill_manager.select_for(
                input_data.requirement, module_type=self.module_name
            )
            if skills:
                skill_section = self.skill_manager.inject(skills, "")

        system_prompt = (
            f"You are an expert software architect for the '{self.module_name}' module.\n"
            f"Capabilities: {capabilities_str}\n"
            f"Analyze the requirement and produce a structured module specification.\n\n"
            f"Output format (JSON):\n{output_schema_str}"
        )

        # Append skill instructions to system prompt
        if skill_section:
            system_prompt += f"\n\n{skill_section}"

        user_prompt = (
            f"## Module: {self.module_name}\n"
            f"## Requirement\n{input_data.requirement}\n\n"
            f"## Constraints\n" + "\n".join(f"- {c}" for c in input_data.constraints) + "\n\n"
            f"## Dependencies\n"
            + "\n".join(f"- {d}" for d in input_data.dependency_interfaces.keys())
            + "\n\n"
            + "## Global Constraints\n"
            + "\n".join(f"- {k}: {v}" for k, v in input_data.global_constraints.items())
            + "\n\nProduce a JSON module specification."
        )

        return system_prompt, user_prompt

    def _build_review_prompt(self, review_input: ReviewInput) -> tuple:
        """构建审查 prompt，返回 (system_prompt, user_prompt)"""
        review_caps = ", ".join(self.review_capabilities) if self.review_capabilities else "general"

        system_prompt = (
            f"You are a code reviewer for the '{review_input.module_name}' module.\n"
            f"Review capabilities: {review_caps}\n"
            f"Review the code against the expected interfaces and acceptance criteria.\n\n"
            'Respond with JSON: {"verdict": "pass|fail|conditional", '
            '"issues": [...], "metrics": {...}}'
        )

        user_prompt = (
            f"## Module: {review_input.module_name}\n\n"
            f"## Code\n```\n{review_input.code_snippet}\n```\n\n"
            f"## Expected Interfaces\n"
            f"{json.dumps(review_input.expected_interfaces, ensure_ascii=False)}\n\n"
            f"## Acceptance Criteria\n"
            + "\n".join(f"- {ac}" for ac in review_input.expected_acceptance_criteria)
            + "\n\nReview the code and respond with JSON."
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

        return ReviewOutput(module=review_input.module_name, verdict="pass")

    def _default_analysis(self, input_data: ExpertInput) -> ExpertOutput:
        """默认分析结果（无 LLM 时）"""
        return ExpertOutput(
            module_name=self.module_name,
            components=[{
                "name": f"{self.module_name.title()}Service",
                "type": "service",
                "description": f"{self.module_name} service",
            }],
            interfaces=[{
                "name": "create",
                "method": "POST",
                "path": f"/api/{self.module_name}/",
            }],
            acceptance_criteria=[f"Create {self.module_name}"],
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


def create_expert_agents(
    schemas_dir: str = "config/schemas",
    agents_config: dict = None,
    llm_provider=None,
    skill_manager=None,
) -> Dict[str, ExpertAgent]:
    """
    动态发现并创建专家 Agent。

    发现机制:
    1. 扫描 schemas/ 目录，找到所有 *_input.json 文件
    2. 从 agents.yaml 的 agents.expert_<module> 读取能力声明
    3. 为每个模块创建一个 ExpertAgent 实例

    Args:
        schemas_dir: Schema 文件目录
        agents_config: agents.yaml 解析后的字典
        llm_provider: LLM Provider 实例
        skill_manager: SkillManager 实例（可选，用于注入技能到 prompt）

    Returns:
        {module_name: ExpertAgent} 字典

    示例:
        # 添加新模块只需:
        # 1. config/schemas/xxx_input.json + xxx_output.json
        # 2. agents.yaml: expert_xxx: { capabilities: [...] }
        # 3. 无需改 Python 代码
        agents = create_expert_agents("config/schemas", agents_config, provider)
        # agents["xxx"] 自动可用
    """
    experts = {}
    agents_config = agents_config or {}
    agents_yaml = agents_config.get("agents", {})

    if not os.path.isdir(schemas_dir):
        return experts

    # 扫描所有 *_input.json 文件
    for filename in sorted(os.listdir(schemas_dir)):
        if not filename.endswith("_input.json"):
            continue

        module_name = filename.replace("_input.json", "")
        input_path = os.path.join(schemas_dir, f"{module_name}_input.json")
        output_path = os.path.join(schemas_dir, f"{module_name}_output.json")

        if not os.path.exists(output_path):
            continue

        # 加载 schemas
        with open(input_path, encoding="utf-8") as f:
            input_schema = json.load(f)
        with open(output_path, encoding="utf-8") as f:
            output_schema = json.load(f)

        # 从 agents.yaml 读取能力声明
        yaml_key = f"expert_{module_name}"
        yaml_config = agents_yaml.get(yaml_key, {})
        capabilities = yaml_config.get("capabilities", [])
        review_capabilities = yaml_config.get("review_capabilities", [])
        version = yaml_config.get("version", "1.0.0")

        experts[module_name] = ExpertAgent(
            agent_id=yaml_key,
            module_name=module_name,
            input_schema=input_schema,
            output_schema=output_schema,
            llm_provider=llm_provider,
            capabilities=capabilities,
            review_capabilities=review_capabilities,
            version=version,
            skill_manager=skill_manager,
        )

    return experts
