# -*- coding: utf-8 -*-
"""
examples/ecommerce_trace.py

端到端可执行 Trace 示例 — 在线商城场景

完整展示方案 D 的编译式流水线：
  1. 需求解析 → 识别 7 个功能模块
  2. 编译器从 Schema 推导全部编排逻辑
  3. 并行分发 → 专家分析 → 整合 Prompt → 生成代码
  4. 代码审查 → 修复循环 → 收敛检测 → 交付

运行方式:
  python -B examples/ecommerce_trace.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.compiler import PipelineCompiler
from tools.compiler.pipeline_compiler import CompiledPipeline
from tools.stores import RequirementStore, InterfaceStore, SpecStore
from tools.messaging import MessageBus, Topic
from tools.quality import QualityEvaluator, ReviewResult, ConvergenceDetector


# ============================================================
# 模块文件名 → 模块名的映射
# ============================================================
MODULE_NAME_MAP = {
    "auth": "authentication",
    "product": "product_catalog",
    "cart": "shopping_cart",
    "order": "order_system",
    "payment": "payment_integration",
    "notification": "notification_service",
    "report": "data_reporting",
}

# 反向映射
FILE_MODULE_MAP = {v: k for k, v in MODULE_NAME_MAP.items()}


def load_schemas(config_dir="config"):
    """加载所有 input/output Schema"""
    schemas_dir = os.path.join(config_dir, "schemas")
    input_schemas = {}
    output_schemas = {}

    for filename in os.listdir(schemas_dir):
        path = os.path.join(schemas_dir, filename)
        with open(path) as f:
            schema = json.load(f)

        if filename.endswith("_input.json"):
            file_module = filename.replace("_input.json", "")
            module_name = MODULE_NAME_MAP.get(file_module, file_module)
            input_schemas[module_name] = schema
        elif filename.endswith("_output.json"):
            file_module = filename.replace("_output.json", "")
            module_name = MODULE_NAME_MAP.get(file_module, file_module)
            output_schemas[module_name] = schema

    return input_schemas, output_schemas


def simulate_expert_analysis(module_name, input_schema, context_strategy):
    """模拟专家 Agent 分析（实际由 LLM 执行）"""
    # 根据 Schema 特征生成模块规格
    spec = {
        "module_name": module_name,
        "components": [],
        "interfaces": [],
        "acceptance_criteria": [],
    }

    props = input_schema.get("properties", {})

    # 根据模块特征生成组件
    if module_name == "authentication":
        spec["components"] = [
            {"name": "AuthService", "type": "service", "description": "认证服务"},
            {"name": "TokenManager", "type": "service", "description": "Token 管理"},
            {"name": "UserModel", "type": "model", "description": "用户模型"},
            {"name": "AuthController", "type": "route", "description": "认证路由"},
        ]
        spec["interfaces"] = [
            {"name": "login", "method": "POST", "path": "/api/auth/login"},
            {"name": "register", "method": "POST", "path": "/api/auth/register"},
            {"name": "refresh", "method": "POST", "path": "/api/auth/refresh"},
            {"name": "logout", "method": "POST", "path": "/api/auth/logout"},
        ]
        spec["acceptance_criteria"] = [
            "用户可使用邮箱密码登录",
            "Token 过期自动刷新",
            "登出后 token 失效",
        ]

    elif module_name == "order_system":
        spec["components"] = [
            {"name": "OrderService", "type": "service", "description": "订单服务"},
            {"name": "OrderModel", "type": "model", "description": "订单模型"},
            {"name": "StateMachine", "type": "util", "description": "订单状态机"},
            {"name": "OrderController", "type": "route", "description": "订单路由"},
        ]
        spec["interfaces"] = [
            {"name": "create_order", "method": "POST", "path": "/api/orders"},
            {"name": "get_order", "method": "GET", "path": "/api/orders/{id}"},
            {"name": "cancel_order", "method": "POST", "path": "/api/orders/{id}/cancel"},
        ]
        spec["acceptance_criteria"] = [
            "用户可创建订单",
            "订单状态正确流转",
            "取消订单释放库存",
        ]

    elif module_name == "payment_integration":
        spec["components"] = [
            {"name": "PaymentService", "type": "service", "description": "支付服务"},
            {"name": "PaymentGateway", "type": "middleware", "description": "支付网关"},
            {"name": "PaymentModel", "type": "model", "description": "支付模型"},
        ]
        spec["interfaces"] = [
            {"name": "create_payment", "method": "POST", "path": "/api/payments"},
            {"name": "refund", "method": "POST", "path": "/api/payments/{id}/refund"},
        ]
        spec["acceptance_criteria"] = [
            "支付请求幂等处理",
            "退款金额不超过原支付金额",
            "支付失败正确回滚",
        ]

    else:
        # 通用模块
        spec["components"] = [
            {"name": f"{module_name.title()}Service", "type": "service", "description": f"{module_name} 服务"},
            {"name": f"{module_name.title()}Model", "type": "model", "description": f"{module_name} 模型"},
            {"name": f"{module_name.title()}Controller", "type": "route", "description": f"{module_name} 路由"},
        ]
        spec["interfaces"] = [
            {"name": "create", "method": "POST", "path": f"/api/{module_name}/"},
            {"name": "get", "method": "GET", "path": f"/api/{module_name}/{{id}}"},
        ]
        spec["acceptance_criteria"] = [
            f"可创建 {module_name}",
            f"可查询 {module_name}",
        ]

    return spec


def simulate_code_review(module_name, code_snippet):
    """模拟代码审查（实际由 LLM 执行）"""
    import random
    # 模拟：大部分模块通过，偶尔有问题
    if module_name == "shopping_cart" and random.random() < 0.5:
        return {
            "verdict": "fail",
            "issues": [
                {
                    "issue_id": "I001",
                    "severity": "major",
                    "location": "cart/service.py:42",
                    "description": "价格计算未考虑并发修改",
                    "suggestion": "在 calculate_total 方法中添加乐观锁",
                    "fix_type": "add_concurrency_control",
                }
            ],
        }
    return {"verdict": "pass", "issues": []}


def run_trace():
    print("=" * 70)
    print("  Claude-Codex Multi-Agent — 端到端 Trace")
    print("  场景: 构建在线商城（7 个功能模块）")
    print("=" * 70)

    # ========================================
    # Step 1: 需求解析
    # ========================================
    print("\n[Step 1] Codex 解析需求")
    print("-" * 50)
    raw_requirement = "构建一个在线商城，支持用户注册登录、商品浏览、购物车、下单、支付，以及订单通知和数据报表"
    print(f"  输入: {raw_requirement}")

    functional_modules = list(MODULE_NAME_MAP.values())
    print(f"  识别模块: {functional_modules}")

    # ========================================
    # Step 2: 编译流水线
    # ========================================
    print("\n[Step 2] 编译流水线")
    print("-" * 50)

    input_schemas, output_schemas = load_schemas()
    compiler = PipelineCompiler()

    print(f"  加载 input_schema: {len(input_schemas)} 个")
    print(f"  加载 output_schema: {len(output_schemas)} 个")

    compiled = compiler.compile(output_schemas, input_schemas=input_schemas)

    print(f"  编译完成:")
    print(f"    - 上下文策略: {len(compiled.context_strategies)} 个")
    print(f"    - 实现顺序: {compiled.implementation_order}")
    print(f"    - 修复模板: {len(compiled.fix_templates)} 个")
    print(f"    - 质量门禁: {len(compiled.quality_gates.gates)} 个")

    # ========================================
    # Step 3: 上下文注入推导
    # ========================================
    print("\n[Step 3] 上下文注入推导")
    print("-" * 50)

    for module_name, strategy in compiled.context_strategies.items():
        needs = []
        if strategy.needs_security_context:
            needs.append("安全上下文")
        if strategy.needs_compliance_context:
            needs.append("合规上下文")
        if strategy.needs_business_rules:
            needs.append("业务规则")
        if strategy.needs_search_requirements:
            needs.append("搜索需求")
        if strategy.needs_global_constraints:
            needs.append("全局约束")
        print(f"    {module_name}: {', '.join(needs) if needs else '仅全局约束'}")

    # ========================================
    # Step 4: 模拟专家并行分析
    # ========================================
    print("\n[Step 4] 专家 Agent 并行分析")
    print("-" * 50)

    all_specs = {}
    for module_name in compiled.implementation_order:
        input_schema = input_schemas.get(module_name, {})
        strategy = compiled.context_strategies.get(module_name)
        spec = simulate_expert_analysis(module_name, input_schema, strategy)
        all_specs[module_name] = spec
        print(f"    {module_name}: {len(spec['components'])} 组件, {len(spec['interfaces'])} 接口")

    # ========================================
    # Step 5: Prompt 模板生成
    # ========================================
    print("\n[Step 5] Prompt 模板生成")
    print("-" * 50)

    prompt = compiled.prompt_template.template_str
    print(f"  模板长度: {len(prompt)} 字符")
    print(f"  包含模块: {len(compiled.implementation_order)} 个")
    print(f"  前 200 字预览:")
    print(f"    {prompt[:200]}...")

    # ========================================
    # Step 6: 模拟代码生成 + 审查
    # ========================================
    print("\n[Step 6] 代码生成 + 审查")
    print("-" * 50)

    review_results = []
    for module_name in compiled.implementation_order:
        review = simulate_code_review(module_name, "code_snippet")
        review_results.append(ReviewResult(
            module=module_name,
            verdict=review["verdict"],
            issues=review.get("issues", []),
        ))
        status = "✓" if review["verdict"] == "pass" else "✗"
        issues_count = len(review.get("issues", []))
        print(f"    {status} {module_name}: {issues_count} issues")

    # ========================================
    # Step 7: 质量评估
    # ========================================
    print("\n[Step 7] 质量评估")
    print("-" * 50)

    evaluator = QualityEvaluator(quality_gates=compiled.quality_gates)
    report = evaluator.evaluate(review_results, iteration=0)

    print(f"  质量评分: {report.quality_score:.2f}")
    print(f"  是否通过: {'是' if report.passed else '否'}")
    print(f"  失败门禁: {len(report.failed_gates)} 个")
    print(f"  收敛状态: {report.convergence_status}")

    # ========================================
    # Step 8: 修复循环（如有）
    # ========================================
    if not report.passed:
        print("\n[Step 8] 修复循环")
        print("-" * 50)

        detector = ConvergenceDetector(max_iterations=3)
        iteration = 0
        quality_score = report.quality_score

        while True:
            should_continue, reason = detector.should_continue(
                iteration=iteration,
                quality_score=quality_score,
                has_critical=report.has_critical,
            )
            print(f"  迭代 {iteration + 1}: {reason}")

            if not should_continue:
                break

            # 模拟修复后重新审查
            iteration += 1
            # 提升质量评分
            quality_score = min(1.0, quality_score + 0.1)
            report = evaluator.evaluate(review_results, iteration=iteration)

    # ========================================
    # 最终结果
    # ========================================
    print("\n" + "=" * 70)
    print("  Trace 完成")
    print("=" * 70)
    print(f"  模块数: {len(compiled.implementation_order)}")
    print(f"  质量评分: {report.quality_score:.2f}")
    print(f"  最终状态: {report.convergence_status}")
    print(f"  修复模板规则: {sum(len(ft.rules) for ft in compiled.fix_templates.values())} 个")
    print(f"  质量门禁: {len(compiled.quality_gates.gates)} 个")
    print()

    return compiled, report


if __name__ == "__main__":
    run_trace()
