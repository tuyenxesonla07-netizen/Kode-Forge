#!/usr/bin/env python3
"""
scripts/generate_api_key.py — 生成安全 API Key + SHA-256 哈希。

用法:
    python scripts/generate_api_key.py
    python scripts/generate_api_key.py --count 3
    python scripts/generate_api_key.py --env  # 输出为 .env 格式

输出:
    - 原始 API Key（仅显示一次，请立即复制）
    - SHA-256 哈希（用于 CC_API_KEYS 环境变量）
"""

from __future__ import annotations

import argparse
import hashlib
import secrets
import sys


def generate_api_key(length: int = 48) -> str:
    """生成安全的随机 API Key"""
    return f"cc-{secrets.token_urlsafe(length)}"


def hash_api_key(api_key: str) -> str:
    """计算 API Key 的 SHA-256 哈希"""
    return hashlib.sha256(api_key.encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description="生成安全 API Key")
    parser.add_argument("--count", type=int, default=1, help="生成数量 (默认 1)")
    parser.add_argument("--env", action="store_true", help="输出为 .env 格式")
    args = parser.parse_args()

    if args.count < 1:
        print("Error: --count must be >= 1", file=sys.stderr)
        sys.exit(1)

    keys = []
    for i in range(args.count):
        key = generate_api_key()
        key_hash = hash_api_key(key)
        keys.append((key, key_hash))

    if args.env:
        # 输出为 .env 格式
        print("# 复制以下内容到你的 .env 文件")
        print("# 注意：原始 Key 仅显示一次，请立即复制保存！")
        print()
        for i, (key, key_hash) in enumerate(keys):
            if args.count > 1:
                print(f"# Key {i+1}")
            print(f"# CC_API_KEY={key}  # 原始 Key（仅客户端保存）")
            print(f"CC_API_KEYS={key_hash}  # 哈希值（放入服务器环境变量）")
            print()
    else:
        # Human-readable format
        print("=" * 60)
        print("  API Key Generator")
        print("=" * 60)
        for i, (key, key_hash) in enumerate(keys):
            if args.count > 1:
                print(f"\n--- Key {i+1} ---")
            print(f"\n Raw Key (show once, copy now):")
            print(f"   {key}")
            print(f"\n SHA-256 Hash (put in CC_API_KEYS):")
            print(f"   {key_hash}")
        print("\n" + "=" * 60)
        print(" [!] Raw key shown only once — copy it now!")
        print(" [!] Only put the hash in server env vars")
        print("=" * 60)


if __name__ == "__main__":
    main()
