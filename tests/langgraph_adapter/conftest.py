# tests/langgraph_adapter/conftest.py

"""
Shared fixtures for langgraph_adapter tests.
"""

import pytest
from tools.workflow.nodes import WorkflowNode, NodeType


@pytest.fixture
def simple_llm_node():
    return WorkflowNode(
        id="auth_gen",
        type=NodeType.LLM,
        name="Generate auth module",
        config={"prompt_template": "Generate authentication module code"},
    )


@pytest.fixture
def simple_workflow():
    """创建一个简单的 Workflow 对象（模拟）。"""
    from tools.workflow.engine import Workflow

    nodes = {
        "auth_gen": WorkflowNode(
            id="auth_gen",
            type=NodeType.LLM,
            config={"prompt_template": "Generate auth code"},
        ),
        "db_gen": WorkflowNode(
            id="db_gen",
            type=NodeType.LLM,
            inputs=["auth_gen"],
            config={"prompt_template": "Generate database code based on {{auth_gen}}"},
        ),
        "deploy_check": WorkflowNode(
            id="deploy_check",
            type=NodeType.HUMAN,
            inputs=["db_gen"],
            config={"prompt": "确认部署？", "risk_level": "high"},
        ),
    }
    edges = {
        "auth_gen": ["db_gen"],
        "db_gen": ["deploy_check"],
    }
    return Workflow(id="test_pipeline", name="Test Pipeline", nodes=nodes, edges=edges)
