# tools/cli/rag.py
"""RAG sub-commands: query, search."""

from __future__ import annotations

import argparse
from typing import Any


def _make_pipeline() -> Any:
    from tools.rag import RAGPipeline, RAGConfig, Document
    config = RAGConfig()
    pipeline = RAGPipeline(config)
    docs = [
        Document(content="Python is a high-level programming language with dynamic semantics.", source="wiki_python"),
        Document(content="Machine learning enables systems to learn and improve from experience.", source="wiki_ml"),
        Document(content="Docker is a platform for developing and running applications in containers.", source="docs_docker"),
        Document(content="REST APIs use HTTP methods to interact with resources in web services.", source="docs_rest"),
    ]
    pipeline.ingest(docs)
    return pipeline


def cmd_query(args: argparse.Namespace) -> None:
    pipeline = _make_pipeline()
    result = pipeline.query(args.text)

    print(f"\n  Query: {args.text}")
    print(f"  {'─' * 50}")
    print(f"  Answer: {result.answer[:300]}")
    print(f"  Sources ({len(result.documents)}):")
    for doc in result.documents[:3]:
        print(f"    • {doc.source}: {doc.content[:80]}...")
    print(f"  Latency: {result.metadata.get('latency_ms', 0):.0f}ms\n")


def cmd_search(args: argparse.Namespace) -> None:
    pipeline = _make_pipeline()
    result = pipeline.query(args.text)

    print(f"\n  Search: {args.text}")
    print(f"  {'─' * 50}")
    for i, doc in enumerate(result.documents[:5], 1):
        score = result.scores[i - 1] if i <= len(result.scores) else 0.0
        print(f"  {i}. [{score:.3f}] {doc.source}")
        print(f"     {doc.content[:100]}...")
    print()
