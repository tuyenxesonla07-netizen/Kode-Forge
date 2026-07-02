# ADR-0004: Hash-Chained 审计日志

## 状态
Accepted (V0.4.0 F3)

## 背景

企业审批系统需要**防篡改**的审计日志。普通日志可被攻击者修改后不留痕迹。需要一种机制使得：
1. 任何历史记录的修改都会被检测到
2. 记录之间形成因果链，插入/删除记录会破坏链条

## 决策

采用 **SHA-256 哈希链**（类似区块链的简化版）：

```python
GENESIS_HASH = "0" * 64

def _compute_hash(prev_hash: str, event: dict) -> str:
    """SHA256(prev_hash + canonical_json(event))"""
    canonical = json.dumps(event, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(
        (prev_hash + canonical).encode("utf-8")
    ).hexdigest()
```

### 链结构

```
Record 0: event=approval_requested, prev_hash=0000...0000, hash=H0
Record 1: event=escalated,          prev_hash=H0,          hash=H1
Record 2: event=approved,           prev_hash=H1,          hash=H2
```

### 验证算法

```python
def verify_chain(self) -> tuple[bool, int]:
    """返回 (is_valid, last_valid_idx)"""
    for i, record in enumerate(self._records):
        expected = self._compute_hash(record.prev_hash, record.event)
        if expected != record.hash:
            return False, i - 1
    return True, len(self._records) - 1
```

### 为什么不用 Merkle Tree？

Merkle Tree 适合大量记录的**快速单点验证**（O(log n)）。审批审计日志通常为顺序写入、全量验证，哈希链的 O(n) 完全足够，且实现更简单（~100 行）。

## 后果

**优点**：
- 实现极简（1 个函数 + 1 个验证循环）
- 任何篡改（修改、插入、删除）都会被 `verify_chain()` 检测
- 无需外部依赖（`hashlib` 是标准库）

**缺点**：
- 无法防"全量替换"攻击（攻击者可重新计算整条链）
- 需要配合只读存储或数字签名实现真正的不可否认性
- 日志大小线性增长（无 pruning 策略）

## 相关

- ADR-0003: 审批状态机
- `tools/hitl/audit_chain.py` — HashChainedAuditLog 实现
