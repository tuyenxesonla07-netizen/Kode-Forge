# scripts/benchmark_runtime.py

"""
scripts/benchmark_runtime.py — V0.5.0 运行时性能基准测试。

测量:
    - 冷启动延迟 (首次创建 orchestrator)
    - 热路径延迟 (复用 orchestrator)
    - 内存占用 (100 次对话)
    - 意图分类速度

用法:
    python scripts/benchmark_runtime.py
    python scripts/benchmark_runtime.py --iterations 50
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
import tracemalloc


def benchmark_cold_start(iterations: int = 10) -> dict:
    """测量冷启动延迟。"""
    from agents.runtime.orchestrator import AgentOrchestrator

    latencies = []
    for _ in range(iterations):
        t0 = time.monotonic()
        orch = AgentOrchestrator()
        t1 = time.monotonic()
        latencies.append((t1 - t0) * 1000)

    return {
        "name": "cold_start_ms",
        "iterations": iterations,
        "mean": statistics.mean(latencies),
        "median": statistics.median(latencies),
        "min": min(latencies),
        "max": max(latencies),
        "stdev": statistics.stdev(latencies) if len(latencies) > 1 else 0,
    }


def benchmark_hot_path(iterations: int = 50) -> dict:
    """测量热路径延迟 (同步 stub 模式)。"""
    from agents.runtime.orchestrator import AgentOrchestrator

    orch = AgentOrchestrator()
    # 预热
    orch.run_agent_sync("warmup")

    latencies = []
    for i in range(iterations):
        t0 = time.monotonic()
        orch.run_agent_sync(f"测试消息 {i}")
        t1 = time.monotonic()
        latencies.append((t1 - t0) * 1000)

    return {
        "name": "hot_path_ms",
        "iterations": iterations,
        "mean": statistics.mean(latencies),
        "median": statistics.median(latencies),
        "min": min(latencies),
        "max": max(latencies),
        "stdev": statistics.stdev(latencies) if len(latencies) > 1 else 0,
    }


def benchmark_intent_classification(iterations: int = 100) -> dict:
    """测量意图分类速度。"""
    from agents.supervisor.router import SupervisorRouter

    router = SupervisorRouter()
    test_messages = [
        "生成用户登录模块",
        "修复 bug",
        "检查代码质量",
        "什么是依赖注入",
        "批准这个请求",
    ]

    latencies = []
    for i in range(iterations):
        msg = test_messages[i % len(test_messages)]
        t0 = time.monotonic()
        router._classify_intent(msg)
        t1 = time.monotonic()
        latencies.append((t1 - t0) * 1000)

    return {
        "name": "intent_classification_us",
        "iterations": iterations,
        "mean": statistics.mean(latencies) * 1000,  # convert to microseconds
        "median": statistics.median(latencies) * 1000,
        "min": min(latencies) * 1000,
        "max": max(latencies) * 1000,
    }


def benchmark_memory(n_conversations: int = 100) -> dict:
    """测量内存占用。"""
    from agents.runtime.orchestrator import AgentOrchestrator
    from tools.server.agent_conversation import AgentConversationManager

    tracemalloc.start()

    mgr = AgentConversationManager(max_conversations=200)
    for i in range(n_conversations):
        cid = mgr.create()
        mgr.send_message_sync(cid, f"消息 {i}") if hasattr(mgr, "send_message_sync") else None

    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return {
        "name": "memory_bytes",
        "n_conversations": n_conversations,
        "current_kb": current / 1024,
        "peak_kb": peak / 1024,
        "per_conversation_bytes": current / n_conversations if n_conversations > 0 else 0,
    }


def print_result(result: dict) -> None:
    """打印基准结果。"""
    print(f"\n{'='*50}")
    print(f"  Benchmark: {result['name']}")
    print(f"{'='*50}")
    for key, value in result.items():
        if key == "name":
            continue
        if isinstance(value, float):
            if "us" in result["name"]:
                print(f"  {key}: {value:.1f} μs")
            elif "bytes" in result["name"] or "kb" in key:
                print(f"  {key}: {value:,.1f}")
            else:
                print(f"  {key}: {value:.3f} ms")
        else:
            print(f"  {key}: {value}")


def main():
    parser = argparse.ArgumentParser(description="V0.5.0 Runtime Benchmark")
    parser.add_argument("--iterations", type=int, default=20, help="迭代次数")
    parser.add_argument("--skip-memory", action="store_true", help="跳过内存基准")
    args = parser.parse_args()

    print("=" * 50)
    print("  V0.5.0 Runtime Performance Benchmark")
    print("=" * 50)

    # 1. 冷启动
    result = benchmark_cold_start(iterations=min(args.iterations, 10))
    print_result(result)

    # 2. 热路径
    result = benchmark_hot_path(iterations=args.iterations)
    print_result(result)

    # 3. 意图分类
    result = benchmark_intent_classification(iterations=max(args.iterations * 5, 100))
    print_result(result)

    # 4. 内存
    if not args.skip_memory:
        result = benchmark_memory(n_conversations=min(args.iterations * 5, 100))
        print_result(result)

    print(f"\n{'='*50}")
    print("  Benchmark complete.")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
