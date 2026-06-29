# tests/integration/test_mcp_server.py

"""
MCP 服务端单元测试。

覆盖:
- handle_message: initialize, tools/list, tools/call, unknown method
- ToolRegistry: register, call, to_mcp_format
- MCPServer._handle_request (FastAPI route handler)
"""

import asyncio
import pytest
from unittest.mock import MagicMock

from tools.mcp.tool_registry import ToolRegistry
from tools.mcp.mcp_server import MCPServer


# ─── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def sample_handler():
    """同步工具 handler"""
    def handler(code: str, **kwargs):
        return {"valid": True, "errors": []}
    return handler


@pytest.fixture
def async_handler():
    """异步工具 handler"""
    async def handler(query: str, **kwargs):
        return [{"content": f"Result for: {query}", "source": "kb"}]
    return handler


@pytest.fixture
def registry(sample_handler):
    """预注册工具的 ToolRegistry"""
    reg = ToolRegistry()
    reg.register_func(
        name="validate_python",
        description="验证 Python 代码语法",
        input_schema={
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
        },
        handler=sample_handler,
    )
    reg.register_func(
        name="search_knowledge",
        description="知识库检索",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        handler=async_handler,
    )
    return reg


@pytest.fixture
def server(registry):
    """MCPServer 实例"""
    return MCPServer(registry, host="localhost", port=9000)


# ─── ToolRegistry 测试 ────────────────────────────────────


class TestToolRegistry:
    """ToolRegistry 工具注册与发现"""

    def test_register_and_list(self, registry):
        tools = registry.list_tools()
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert names == {"validate_python", "search_knowledge"}

    def test_get_tool(self, registry):
        tool = registry.get_tool("validate_python")
        assert tool is not None
        assert tool.name == "validate_python"

    def test_get_tool_not_found(self, registry):
        assert registry.get_tool("nonexistent") is None

    def test_register_overwrite_warning(self, registry, caplog):
        """重复注册同名工具应发出警告"""
        registry.register_func(
            name="validate_python",
            description="duplicate",
            input_schema={},
            handler=lambda: None,
        )
        assert "Overwriting" in caplog.text or "Registered" in caplog.text

    def test_unregister(self, registry):
        assert registry.unregister("validate_python") is True
        assert registry.get_tool("validate_python") is None

    def test_unregister_not_found(self, registry):
        assert registry.unregister("nonexistent") is False

    @pytest.mark.asyncio
    async def test_call_sync_handler(self, registry):
        result = await registry.call("validate_python", {"code": "x = 1"})
        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_call_async_handler(self):
        """异步 handler 注册和调用"""
        async def _search(query: str, **kwargs):
            return [{"content": f"Result for: {query}", "source": "kb"}]

        reg = ToolRegistry()
        reg.register_func(
            name="async_search",
            description="异步知识库检索",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            handler=_search,
        )
        result = await reg.call("async_search", {"query": "auth"})
        assert len(result) == 1
        assert "Result for: auth" in result[0]["content"]

    @pytest.mark.asyncio
    async def test_call_not_found(self, registry):
        with pytest.raises(KeyError, match="Tool not found"):
            await registry.call("nonexistent", {})

    @pytest.mark.asyncio
    async def test_call_handler_error(self, registry):
        """handler 抛出异常应转为 RuntimeError"""
        def bad_handler(**kwargs):
            raise ValueError("broken")

        registry.register_func(
            name="bad_tool",
            description="",
            input_schema={},
            handler=bad_handler,
        )
        with pytest.raises(RuntimeError, match="Tool execution failed"):
            await registry.call("bad_tool", {})

    def test_to_mcp_format(self, registry):
        """MCP 协议格式转换"""
        tools = registry.to_mcp_format()
        assert len(tools) == 2
        for t in tools:
            assert "name" in t
            assert "description" in t
            assert "inputSchema" in t
        names = {t["name"] for t in tools}
        assert "validate_python" in names


# ─── MCPServer.handle_message 测试 ────────────────────────


class TestMCPServerHandleMessage:
    """MCPServer.handle_message JSON-RPC 2.0 处理"""

    @pytest.mark.asyncio
    async def test_initialize(self, server):
        msg = {"jsonrpc": "2.0", "id": "req-1", "method": "initialize", "params": {}}
        response = await server.handle_message(msg)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == "req-1"
        assert "result" in response
        assert response["result"]["protocolVersion"] == "2024-11-05"
        assert response["result"]["serverInfo"]["name"] == "claude-codex-multi-agent"
        assert response["result"]["serverInfo"]["version"] == "2.0.0"
        assert "tools" in response["result"]["capabilities"]

    @pytest.mark.asyncio
    async def test_tools_list(self, server):
        msg = {"jsonrpc": "2.0", "id": "req-2", "method": "tools/list", "params": {}}
        response = await server.handle_message(msg)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == "req-2"
        assert "result" in response
        tools = response["result"]["tools"]
        assert len(tools) == 2
        names = {t["name"] for t in tools}
        assert "validate_python" in names
        assert "search_knowledge" in names

    @pytest.mark.asyncio
    async def test_tools_call_sync(self, server):
        msg = {
            "jsonrpc": "2.0",
            "id": "req-3",
            "method": "tools/call",
            "params": {"name": "validate_python", "arguments": {"code": "x = 1"}},
        }
        response = await server.handle_message(msg)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == "req-3"
        assert "result" in response
        assert response["result"]["isError"] is False
        assert "valid" in response["result"]["content"]

    @pytest.mark.asyncio
    async def test_tools_call_async(self):
        """tools/call 调用异步工具"""
        async def _search(query: str, **kwargs):
            return [{"content": f"Async: {query}", "source": "kb"}]

        reg = ToolRegistry()
        reg.register_func(
            name="async_search",
            description="异步搜索",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            handler=_search,
        )
        srv = MCPServer(reg, host="localhost", port=9001)
        msg = {
            "jsonrpc": "2.0",
            "id": "req-async",
            "method": "tools/call",
            "params": {"name": "async_search", "arguments": {"query": "test"}},
        }
        response = await srv.handle_message(msg)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == "req-async"
        assert response["result"]["isError"] is False
        assert "Async: test" in response["result"]["content"]

    @pytest.mark.asyncio
    async def test_tools_call_not_found(self, server):
        msg = {
            "jsonrpc": "2.0",
            "id": "req-5",
            "method": "tools/call",
            "params": {"name": "nonexistent", "arguments": {}},
        }
        response = await server.handle_message(msg)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == "req-5"
        assert "error" in response
        assert response["error"]["code"] == -32603  # Internal error

    @pytest.mark.asyncio
    async def test_unknown_method(self, server):
        msg = {"jsonrpc": "2.0", "id": "req-6", "method": "unknown/method", "params": {}}
        response = await server.handle_message(msg)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == "req-6"
        assert "error" in response
        assert response["error"]["code"] == -32601  # Method not found
        assert "unknown/method" in response["error"]["message"]

    @pytest.mark.asyncio
    async def test_notification_no_response(self, server):
        """没有 id 的消息是通知，不返回响应（JSON-RPC 2.0 规范）"""
        msg = {"jsonrpc": "2.0", "method": "initialize", "params": {}}
        response = await server.handle_message(msg)
        assert response is None

    @pytest.mark.asyncio
    async def test_handler_exception_returns_error(self, server):
        """handler 异常应返回 JSON-RPC error"""
        def broken(**kwargs):
            raise RuntimeError("boom")

        server.registry.register_func(
            name="broken",
            description="",
            input_schema={},
            handler=broken,
        )
        msg = {
            "jsonrpc": "2.0",
            "id": "req-7",
            "method": "tools/call",
            "params": {"name": "broken", "arguments": {}},
        }
        response = await server.handle_message(msg)

        assert "error" in response
        assert response["error"]["code"] == -32603


# ─── MCPServer._handle_request 测试 ───────────────────────


class TestMCPServerHandleRequest:
    """MCPServer._handle_request（FastAPI 路由包装）"""

    @pytest.mark.asyncio
    async def test_handle_request_delegates(self, server):
        """_handle_request 应委托给 handle_message"""
        request = {"jsonrpc": "2.0", "id": "r1", "method": "tools/list", "params": {}}
        response = await server._handle_request(request)
        assert response["id"] == "r1"
        assert "result" in response


# ─── MCPServer.stop 测试 ──────────────────────────────────


class TestMCPServerStop:
    """MCPServer.stop"""

    @pytest.mark.asyncio
    async def test_stop_no_server(self, server):
        """未启动服务时调用 stop 不应报错"""
        server._server = None
        await server.stop()  # Should not raise

    @pytest.mark.asyncio
    async def test_stop_with_server(self):
        """已启动服务时调用 stop 应设置 should_exit"""
        registry = ToolRegistry()
        server = MCPServer(registry, host="localhost", port=9001)
        mock_server = MagicMock()
        server._server = mock_server
        await server.stop()
        assert mock_server.should_exit is True


# ─── 集成: MCPServer + ToolRegistry 端到端 ────────────────


class TestMCPServerIntegration:
    """端到端集成测试：ToolRegistry + MCPServer"""

    @pytest.mark.asyncio
    async def test_full_json_rpc_exchange(self, server):
        """完整 JSON-RPC 交换: initialize → tools/list → tools/call"""
        # Step 1: initialize
        init_resp = await server.handle_message(
            {"jsonrpc": "2.0", "id": "init-1", "method": "initialize", "params": {}}
        )
        assert "result" in init_resp
        assert init_resp["result"]["protocolVersion"] == "2024-11-05"

        # Step 2: tools/list
        list_resp = await server.handle_message(
            {"jsonrpc": "2.0", "id": "list-1", "method": "tools/list", "params": {}}
        )
        assert "result" in list_resp
        tool_count = len(list_resp["result"]["tools"])
        assert tool_count >= 2

        # Step 3: tools/call
        call_resp = await server.handle_message({
            "jsonrpc": "2.0",
            "id": "call-1",
            "method": "tools/call",
            "params": {
                "name": "validate_python",
                "arguments": {"code": "print('hello')"},
            },
        })
        assert "result" in call_resp
        assert call_resp["result"]["isError"] is False

    @pytest.mark.asyncio
    async def test_concurrent_requests(self, server):
        """并发请求处理"""
        messages = [
            {"jsonrpc": "2.0", "id": f"req-{i}", "method": "tools/list", "params": {}}
            for i in range(5)
        ]
        results = await asyncio.gather(
            *[server.handle_message(msg) for msg in messages]
        )
        assert len(results) == 5
        for i, result in enumerate(results):
            assert result["id"] == f"req-{i}"
            assert "result" in result
