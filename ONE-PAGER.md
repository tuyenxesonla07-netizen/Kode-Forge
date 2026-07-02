# KodeForge — ONE-PAGER

## 这个项目解决什么问题？

企业用 AI 写代码最大的顾虑不是「写得不够快」，而是「不知道能不能信、敢不敢上线」。

**KodeForge 让企业敢用 AI 生成代码并过 SOC2/HIPAA 审计。**

---

## 一句话定位

> 不做"AI编码助手"（红海，50+ 竞品）。做"AI编码的合规基础设施"——代码生成之后的**质量守门员**。

---

## 目标用户

| 场景 | 用户 | 痛点 |
|------|------|------|
| 金融核心系统 | 技术负责人 | AI 代码需过 SOC2，每次变更要留审计追踪 |
| 医疗健康应用（HIPAA） | CTO | AI 生成代码涉及 ePHI 时，必须有不可篡改日志 + 人工签署确认 |
| 政务/央国企数字化 | 项目负责人 | 政府采购要求代码来源可追溯、AI 辅助必须留痕 |
| 任何 500+ 人研发团队 | 工程效能负责人 | 大规模采用 AI Coding 后，质量收敛没有系统级保障 |

---

## 核心差异

| 能力 | KodeForge | Cursor/Copilot | CodeRabbit | Dify/LangGraph |
|------|-----------|----------------|------------|----------------|
| 代码生成 | ✅ Schema驱动 | ✅ 通用 | ❌（只做Review） | ✅ Agent框架 |
| Quality Gate 收敛 | ✅ 内置，可配 | ❌ | ❌ | ❌ 需自建 |
| HITL 不可绕过审批 | ✅ 架构一等公民 | ❌ | ❌ | ❌ |
| SOC2/HIPAA 审计追踪 | ✅ 原生日志 | ❌ | ❌ | ⚠️ 部分 |
| RAG 双引擎辅助生成 | ✅ | ❌ | ❌ | ⚠️ 单引擎 |

---

## 工作流程

```
用户写 JSON Schema（模块契约）
  ↓
PipelineCompiler 自动执行顺序、上下文、质量门禁
  ↓
多 ExpertAgent 并行生成代码（RAG + Skills 注入）
  ↓
OutputGuard 安全扫描（注入检测 + PII 掩码）
  ↓
QualityEvaluator 评分 + ConvergenceDetector 收敛检测
  ↓  未收敛 → 自动修复 → 再评估（有界重试）
  ↓  收敛失败 → HITL 人工审批节点（强制阻断）
  ↓
AuditLog 记录完整审计追踪 ← SOC2/HIPAA 合规 ✅
```

---

## 合规对应（为什么这件事现在是刚需）

**SOC2（CC6+CC7+CC8）要求：**
1. 哪些代码是 AI 生成的 → `AuditLog` 自动标记来源
2. 谁在何时审核并批准了 AI 输出 → `HITLApproval` 节点留痕
3. 模型版本 + prompt 可追溯 → `Tracer` 全链路记录
4. 审计日志不可篡改，保留期 6 年 → `AuditLog` 设计符合

**HIPAA 2025 OCR 最终指引：**
- AI 生成代码部署前必须有人签署 `HumanAttestation`
- KodeForge 的 `HITLApprovalHandler` 天然对应此要求

---

## 竞品赛道

| 维度 | 最强竞品 | KodeForge 状态 |
|------|---------|--------------|
| Quality Gate | Snyk+Qodo（安全维度） | 全量质量维度 — 市场空白 ✅ |
| HITL+审计 | GitHub Compliance Mode（Beta，点状） | 管线级一体化 ✅ |
| Schema-first 管线 | OpenAPI Generator（仅API层） | 扩展到业务代码层 ✅ |
| 编排框架 | LangGraph | 定位「LangGraph 之上的质量层」，不对抗 ✅ |

---

## 当前状态

- **版本**：v0.4.0.dev0（内部开发中）
- **测试**：1095 passed, 13 skipped（已建立质量基线）
- **模块**：PipelineCompiler, RAG双引擎, Quality Gate, HITL, AuditLog, WorkflowDAG
- **下一步**：
  - P1：质量门禁独立为可拔插库（`pip install kodeforge-quality`）
  - P2：选定垂直行业（金融/医疗/政务）做种子客户验证
  - P3：CI/CD 集成（GitHub Actions / GitLab CI）+ SOC2 认证指引文档

---

## 联系方式

项目路径：`D:\IDLE\Kode-Forge\project\KodeForge\`
文档：`CLAUDE.md`（内部工程师）｜ `README.md`（用户）
