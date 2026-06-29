# tools/exceptions.py
"""
项目统一异常体系。

所有自定义异常继承自 CCBaseException，调用方可分级捕获：
    try:
        ...
    except CompilationError:
        # 编译阶段错误
    except WorkflowExecutionError:
        # 工作流执行错误
    except CCBaseException:
        # 兜底：任何 CC 异常
"""


class CCBaseException(Exception):
    """所有 CC 异常的基类"""
    pass


# ── Compiler 异常 ──

class CompilationError(CCBaseException):
    """Schema 编译失败（格式错误、依赖缺失等）"""
    pass


class DependencyCycleError(CompilationError):
    """模块依赖存在环"""
    def __init__(self, cycle: list[str]):
        self.cycle = cycle
        super().__init__(f"Dependency cycle detected: {' → '.join(cycle)}")


class DependencyNotFoundError(CompilationError):
    """模块依赖的模块不存在"""
    def __init__(self, module: str, missing_dep: str):
        self.module = module
        self.missing_dep = missing_dep
        super().__init__(f"Module '{module}' depends on '{missing_dep}' which does not exist")


# ── Workflow 异常 ──

class WorkflowExecutionError(CCBaseException):
    """工作流节点执行失败"""
    pass


class WorkflowPermissionError(WorkflowExecutionError):
    """节点权限校验失败"""
    def __init__(self, node_id: str, missing: list[str]):
        self.node_id = node_id
        self.missing = missing
        super().__init__(f"Node '{node_id}' missing permissions: {missing}")


class WorkflowTimeoutError(WorkflowExecutionError):
    """节点执行超时"""
    pass


# ── LLM 异常 ──

class LLMError(CCBaseException):
    """LLM 调用失败"""
    pass


class LLMProviderNotFoundError(LLMError):
    """请求的 LLM provider 不可用"""
    def __init__(self, backend: str):
        self.backend = backend
        super().__init__(f"LLM backend '{backend}' is not available")


class LLMResponseError(LLMError):
    """LLM 返回解析失败"""
    pass


# ── Pipeline 异常 ──

class PipelineError(CCBaseException):
    """Pipeline 执行异常基类"""
    pass


class InputGuardError(PipelineError):
    """输入安全检查未通过"""
    def __init__(self, reason: str, pii_found: list[str] | None = None):
        self.reason = reason
        self.pii_found = pii_found or []
        super().__init__(f"Input blocked: {reason}")


class OutputGuardError(PipelineError):
    """输出安全检查未通过"""
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"Output blocked: {reason}")


class QualityGateError(PipelineError):
    """质量门禁未通过（超过最大迭代次数）"""
    def __init__(self, iterations: int, final_score: float):
        self.iterations = iterations
        self.final_score = final_score
        super().__init__(f"Quality gate failed after {iterations} iterations (score: {final_score:.2f})")
