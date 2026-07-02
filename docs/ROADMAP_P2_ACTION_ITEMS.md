# P2 行动项 — Quality Gate 模块化 & 垂直行业切入

> 这个文档是可执行的路线图，不是停留在纸面目标的贪心清单。
> 完成标准：所有「完成标准」标记为 ✅ 时，认为该条目兑现。

---

## P2-A：Quality Gate 独立库结构方案

### 目标

把 `tools/quality/` + `tools/hitl/` + 收敛逻辑打包为一个**可拔插库**，让第三方 Agent 框架（LangGraph / CrewAI / AutoGen）能在自己的 generate 循环里嵌入 KodeForge 的质量门禁：

```python
# 第三方开发者用 3 行接入 KodeForge Quality Gate
from kodeforge.quality import QualityGate, HITLConfig

gate = QualityGate(hitl=HITLConfig(require_human_on=["critical", "high"]))
result = await gate.evaluate(code, issues)
if not result.passed:
    await gate.halt_and_request_approval(state.audit_log)
```

### 完成标准
- [ ] 新建 `packages/kodeforge-quality/`（monorepo 子目录，独立 pyproject.toml）
- [ ] 该包只依赖 `pydantic`（没有 FastAPI / numpy / anthropic 等重型依赖）
- [ ] 从 `tools/quality/` + `tools/hitl/` 中提取核心逻辑至新包
- [ ] 新包独立测试通过 `pytest packages/kodeforge-quality/tests/`
- [ ] 主仓库的 `tools/quality/__init__.py` 改为从 `kodeforge-quality` 导入（向后兼容）
- [ ] 发布到私有 PyPI 或本地产物，`pip install -e "packages/kodeforge-quality/"`

### 推荐目录结构

```
packages/kodeforge-quality/
├── pyproject.toml          # 独立包配置，依赖最小化
├── README.md               # "KodeForge Quality Gate — 嵌入任意 Agent 框架"
├── src/kodeforge/quality/
│   ├── __init__.py         # 导出 QualityGate, QualityEvaluator, ConvergenceDetector
│   ├── evaluator.py        # 评分逻辑（无状态）
│   ├── convergence.py      # 收敛检测
│   ├── hitl.py             # HITL 审批抽象
│   ├── audit.py            # 审计日志数据结构（不含存储实现）
│   └── config.py           # GateConfig, HITLConfig
└── tests/
    ├── test_evaluator.py
    ├── test_convergence.py
    └── test_hitl.py
```

### 关键设计约束

1. **零框架依赖**：只依赖 pydantic v2。不依赖 FastAPI、不依赖 LangGraph、不依赖任何 LLM SDK。这样才能被任意框架嵌入。
2. **同步优先 API**：HITL 是否触发不依赖 asyncio；在异步环境中调用时用 `asyncio.to_thread()`。
3. **不可绕过**：HITL 节点一旦 trigger，代码路径必须阻断，不能 silently pass——这是合规要求，不是产品选项。
4. **审计日志接口化**：包只定义 `AuditLogger` 协议（Protocol），不强制存储实现。由接入方注入。

---

## P2-B：垂直行业切入点（三个候选）

### 🥇 首选：金融核心系统 AI Coding 合规

**理由**
- 银行/保险/证券的 SOC2/等保 合规要求最明确、最刚性
- 「AI 生成代码 → 质量门禁 → 人工审批 → 审计追踪」是完整的已验证采购路径
- 竞品（CodeRabbit、Snyk）只做 review 层，不做生成+质量+审批完整链路

**种子用户假设**
- 城市商业银行科技部（200-500 人规模，采购决策链短）
- 金融科技创业公司（正在接受 SOC2 审核，急需审计工具）

**进入路径**
1. 写一份《金融 AI Coding 等保合规白皮书》（2-4周，方法论来自 NIST AI RMF + 等保2.0 附录）
2. 举办一次小范围闭门分享（10-15 人，目标：银行科技负责人）
3. 拿一个愿意付费试用的「种子合同」

### 🥈 第二选：医疗健康应用 HIPAA 合规

**理由**
- HIPAA 2025 OCR 最终指引明确了 AI 代码部署前必须有人工签署
- 医疗 IT 领域 AI Coding 采纳率低，先发优势明显
- 但决策周期长、采购谨慎

**进入路径**
- 首选切入不是医院，而是**医疗 SaaS 创业公司**（正在 HIPAA 审核阶段）
- 产品价值主张：「帮你快速通过 HIPAA AI Coding 审查，少走6个月弯路」

### 🥉 第三选：政务数字化 AI 辅助审计

**理由**
- 央国企采购 AI 工具必须有审计追踪，这是政府采购基本要求
- 进入门槛高（需要资质），但一旦进入竞争壁垒强

**进入路径**
- 更现实的路径是**通过集成商进入**，而非直接拿下标
- 将 KodeForge 定位为集成商工具箱中的「AI 代码质量合规子模块」

---

## P2-C：CI/CD 集成钩子（面向开发者社群扩散）

### GitHub Actions 集成

```yaml
# .github/workflows/kodeforge-quality.yml
name: KodeForge Quality Gate
on: [pull_request]
jobs:
  quality-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: kodeforge/quality-action@v1   # 待构建
        with:
          schema_dir: config/schemas/
          hitl_threshold: critical
          audit_output: kodeforge-audit.json
```

### 完成标准
- [ ] 发布 `kodeforge/quality-action` GitHub Action（package 化 Action）
- [ ] Action 输出 `kodeforge-audit.json` 作为构建产物
- [ ] 有完整 GitHub 公开仓库演示（demo repo）
- [ ] 在 Hacker News / V2EX / 阮一峰周刊 投放演示链接（技术声量起点）

---

## 工作量估算

| 条目 | 工作量 | 依赖 |
|------|--------|------|
| P2-A Quality Gate 独立库 | 1-2 周 | 无 |
| P2-B 金融白皮书 | 2-4 周 | P2-A 完成（可用真实示例） |
| P2-C GitHub Action | 3-5 天 | P2-A 完成 |
| 小范围闭门分享 | 1-2 周（含组织） | 白皮书完成 |
| **总计** | **4-7 周** | |

---

## 风险与对冲

| 风险 | 概率 | 影响 | 对冲 |
|------|------|------|------|
| Schema-first 门槛劝退早期种子用户 | 高 | 中 | 第一波种子用户主打「合规刚需」，schema 是附带成本 |
| 金融客户决策周期长（6-12月） | 中 | 高 | 同时推进医疗 SaaS 并行不悖 |
| Snyk+Qodo 合并体快速迭代覆盖质量层 | 中 | 高 | 强化 HITL+审计追踪一体化叙事（单点工具难以复制） |
| 独立库提取破坏现有 1095 个测试 | 中 | 中 | 先完整镜像，验证通过后再切换导入路径 |

---

*文档生成时间：2026-07-01 ｜ 下一步：请联系一位金融/医疗行业的技术负责人，做一次 30 分钟的需求验证对话，验证 P2-B 的种子用户假设。*
