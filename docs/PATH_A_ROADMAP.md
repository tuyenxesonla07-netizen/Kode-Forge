# 路径A 发展规划 — 企业 AI Coding 质量平台

> **核心叙事**：不做"AI编码助手"（红海），做"让企业敢用AI写代码的合规基础设施"。
> **市场规模**：Gartner 预测 2027 年 80% 企业将使用 AI 编码工具，Forrester 预测同期 78%
>           将要求 AI 编码工具产出机器可读审计追踪。质量+合规是 AI Coding 的下半场。
> **文档版本**：v1.0 ｜ 生成时间：2026-07-01

---

## 一、战略定位重申

### 一句话

**KodeForge = 代码生成之后的"质量守门员" + "合规留痕员"。**

我们不跟 Cursor/Copilot 拼"写得更快"，我们解决它们解决不了的问题：
- "这段 AI 写的代码，敢上线吗？"
- "审计来了，能证明这段代码经过质量审查和人工审批吗？"
- "开发团队大规模用 AI 后，收敛有没有系统保障？"

### 价值主张矩阵

| 角色 | 痛点 | KodeForge 提供的价值 |
|------|------|---------------------|
| **CTO/技术 VP** | AI 代码质量不可控，上线后出事故 | 有界收敛 + Quality Gate = 质量底线 |
| **合规/安全负责人** | 审计要求知道"AI 写了谁审的" | HITL 不可绕过 + AuditLog 完整追踪 |
| **工程效能负责人** | 大规模用 AI 后良莠不齐 | Schema-first 统一标准，RAG 双引擎保质量 |
| **一线开发者** | 想用 AI 但怕出事背锅 | "系统帮你兜底"，有审批链保护 |

---

## 二、目标用户画像（按付费意愿和决策速度排序）

### Tier 1 - 主攻（2026 H2）

**画像 A：城市商业银行科技部**
- 规模：研发 200-500 人，AI Coding 采纳率 30-60%
- 决策链：CIO → 信息安全官 → 采购委员会（3-6个月）
- 刚性需求：等保2.0 + 银保监会《银行业金融机构数字化转型指引》AI 审计要求
- 付费意愿：年费 50-200 万级，合规预算单独列支
- KodeForge 切入点：「AI 生成核心系统代码的内审合规方案」

**画像 B：正在接受 SOC2 Type II 审核的金融科技/SaaS 创业公司**
- 规模：50-200 人，快速扩张期
- 决策链：CTO 拍板，直接采购（1-3个月）
- 刚性需求：SOC2 审核明确要求 AI 代码变更可追溯
- 付费意愿：年费 10-50 万级，可从研发工具预算中列支
- **这批客户是最好的冷启动对象**——需求真实、决策链短、愿意尝试新工具

### Tier 2 - 扩展（2027）

**画像 C：医疗 SaaS 公司（HIPAA 合规）**
- HIPAA 2025 OCR 最终指引要求 AI 代码部署前人工签署
- 医疗 IT 决策周期长（6-12月），但客单价高

**画像 D：政务数字化项目（等保三级）**
- 必须通过集成商进入，不适合直接触达

### Tier 3 - 长尾（2027+）

**画像 E：500+ 人规模互联网/科技公司**
- 主要卖工程效能，而非合规
- 销售周期长但量大

---

## 三、产品演进路线（4个阶段）

```
Phase 0 (已完成)     Phase 1 (Q3 2026)     Phase 2 (Q4 2026)    Phase 3 (2027 H1)
  核心能力建立          垂直产品化            渠道+生态            规模化
  ─────────────       ──────────────      ──────────────      ──────────────
  多Agent管线          金融垂直版            CI/CD 集成            商业版发布
  Quality Gate         种子客户部署           GitHub Action           SOC2 认证套件
  HITL审批链           白皮书+闭门分享        API 开放平台            渠道合作伙伴
  RAG双引擎            v0.5稳定版           鉴证服务                Horizontal 扩展
```

---

## 四、Phase 1（Q3 2026）：垂直产品化 —「金融核心系统 AI 代码质量平台」

### 4.1 目标

在 Q3 结束前：
- 发布 **KodeForge Quality Gate v0.5**（独立可拔插库）
- 获得 **1 个付费种子客户**（金融或金融科技创业公司）
- 发布 **金融 AI Coding 合规白皮书**（PDF，20-30页，英文+中文）

### 4.2 产品交付物清单

#### 交付物 1：`kodeforge-quality` 独立库（包名：`kodeforge-quality`）

```python
# 用户用法示例
from kodeforge_quality import (
    QualityEvaluator, ConvergenceDetector,
    AuditLogger, HITLRequirement, GateResult
)

evaluator = QualityEvaluator(gates=[...])
report = evaluator.evaluate(review_results)

if not report.passed:
    detector = ConvergenceDetector(max_iterations=3)
    should_fix, reason = detector.should_continue(iteration, report)

    if should_fix:
        # 自动修复回路
        await fix_loop()
    else:
        # HITL 阻断
        raise HITLBlockedException(report.audit_bundle)
```

**完成标准**
- [ ] 仓库结构：`packages/kodeforge-quality/`（详见 ROADMAP_P2_ACTION_ITEMS.md P2-A）
- [ ] 依赖：仅 `pydantic >= 2.0`，零框架依赖
- [ ] 覆盖率：独立测试 ≥ 90%
- [ ] 向后兼容：主仓库 `tools/quality/__init__.py` 改从 `kodeforge-quality` 导入

#### 交付物 2：「金融合规配置文件」预设包

为金融客户提供一个开箱即用的 Quality Gate 配置包，预置三个等级的合规模板：

```
kodeforge_quality/presets/
├── financial/                  # 金融行业预设
│   ├── sox_compliance.json     # SOX 财务报告系统
│   ├── tier3_equ.json          # 等保三级（银行核心系统）
│   └── general.json            # 通用金融合规（默认）
├── hipaa/                      # 医疗行业预设（Phase 2 启用）
│   └── phi_protection.json
└── common/
    ├── minimum.json            # 所有行业通用最小门禁
    └── strict.json             # 严格模式（最高安全）
```

预置文件结构（YAML，人类可读可改）：

```yaml
# kodeforge_quality/presets/financial/general.json
name: "financial-general"
description: "通用金融 AI 代码合规配置（城商行/金融科技）"
version: "0.5.0"
compliance:
  framework: "SOC2-TypeII"
  references:
    - "AICPA CC6/CC7/CC8"
    - "等保2.0 三级"
    - "银保监发〔2022〕2号"
gates:
  - metric: "critical_issues"
    operator: "=="
    threshold: 0
    blocking: true
    severity: "fatal"
    message: "Critical issue detected — requires immediate human review"

  - metric: "quality_score"
    operator: ">="
    threshold: 0.80          # 金融行业比普通严格（一般行业0.70）
    blocking: true

  - metric: "ai_generation_ratio"  # AI 代码占比
    operator: "<="
    threshold: 0.60          # 金融限制 AI 代码不超过 60%
    blocking: false          # 仅警告，不阻断
    severity: "warn"

  - metric: "test_coverage"
    operator: ">="
    threshold: 0.85
    blocking: false          # 强烈建议但不强制

hitl_rules:
  require_human_on:
    - metric: "critical_issues"
      condition: "> 0"
    - metric: "ai_generation_ratio"
      condition: "> 0.60"
    - metric: "sees_pii"
      condition: "== true"
  approver_roles: ["tech_lead", "security_officer"]
  max_approval_hours: 24      # 超过 24h 未审批升级给 CTO

audit:
  retention_days: 2190        # 6年（SOC 2 要求）
  immutable: true             # WORM 存储
  export_formats: ["jsonl", "sarif"]
```

#### 交付物 3：「金融 AI Coding 合规白皮书」

**目标**：建立行业话语权，让金融安全负责人主动搜索到这份文档。

**大纲（20-30页中英文）**
1. AI Coding 在银行业的现状与风险（引用银保监会2022年2号文）
2. SOC2/HIPAA/等保2.0 对 AI 代码的合规要求映射
3. 现有工具（Cursor/Copilot/CodeRabbit）的合规性缺口分析
4. KodeForge Quality Gate 解决方案架构
5. 部署模式：私有化 vs 混合云
6. 审计追踪不可篡改的技术实现（含 AuditLog 数据结构）
7. 某金融科技公司 SOC2 审核案例研究（Phase 2 补充真实数据）
8. 附录：Compliance Checklist（可直接用于采购评审）

### 4.3 种子客户获取路径

**冷启动策略不是"先打磨产品再去找客户"，而是"在打磨过程中同步找到种子用户"。**

#### Week 1-2：建立存在感
- [ ] 在公众号（阿里云开发者/InfoQ/51CTO）发《银行核心系统 AI 代码合规：被忽视的 SOC2 盲区》
- [ ] 在知乎/掘金发《从零搭建 AI 代码审查的质量门禁体系——以某城商行为例》
- [ ] 发推/X：每日一帖 Quality Gate 设计思路（技术长文系列）

#### Week 3-4：触达
- [ ] 目标名单：找 10 个金融科技/城商行的安全负责人（脉脉/LinkedIn）
- [ ] 方式：发一封个性化邮件（不超过200字），核心钩子：「你们 SOC2 审核里 AI 代码审计那块，我有个免费工具可以帮你们省2个月」
- [ ] 目标：获得 3 个 30 分钟对话

#### Week 5-6：深度对话
- [ ] 每个对话用同一个 Discussion Guide（问题清单）
- [ ] 核心验证问题：
  - "你们 AI 写的代码上线前走什么审批流程？"
  - "SOC2 审计员问过 AI 代码问题吗？怎么回答的？"
  - "如果有一个工具能自动生成 SOC2 要求的审计日志，你愿意付多少？"
- [ ] 目标：找到 1 个愿意做付费 POC（概念验证）的客户

#### Week 7-8：POC 部署
- [ ] POC 范围：针对客户一个真实模块，跑完整 Quality Gate
- [ ] POC 交付物：质量报告 + 审计日志 + 改进建议书
- [ ] 目标：1万元级收费，换取真实使用案例和推荐信

### 4.4 阶段性指标（Q3 末）

| 指标 | 达成标准 |
|------|---------|
| `kodeforge-quality` 库 | 独立发布，pip install 可用 |
| 测试覆盖率 | ≥ 90% |
| 金融预设包 | 3个配置文件，覆盖一般/等保三级/SOX |
| 白皮书 | 中英文两版，PDF + HTML |
| 种子客户 | ≥ 1 个付费 POC |
| 社区触达 | 10+ 金融行业深度对话 |
| 公开文章 | ≥ 5 篇技术长文 |

---

## 五、Phase 2（Q4 2026）：渠道与基础设施

### 5.1 目标
- GitHub Action 集成完成（开发者入口）
- SOC2 认证套件文档完成（可直接用于客户采购流程）
- 种子客户 → 2-3个付费合同

### 5.2 关键产品交付

#### GitHub Action：开发者获客入口

```yaml
# 开发者复制粘贴即可用
name: KodeForge Quality Gate
on: [pull_request, push]
jobs:
  quality-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run KodeForge Quality Gate
        uses: kodeforge/quality-action@v1
        with:
          config: kodeforge-compliance.yaml   # 指向预设文件
          audit_output: kodeforge-audit.json
      - name: Upload Audit Log
        uses: actions/upload-artifact@v4
        with:
          name: kodeforge-audit
          path: kodeforge-audit.json
      - name: Check Gate Passed
        run: kodeforge-quality check --from-pr
```

**动作逻辑**：
1. 检测 PR 中 AI 生成的代码（通过注释标签 `// @ai-generated` 或 git blame 元数据）
2. 对 AI 生成文件运行 AST 检查 + LLM Review（可配置 severity 阈值）
3. 如果超过阈值，在 PR 上自动发评论说明问题 + 附加审计追踪
4. 输出 `kodeforge-audit.json`（SOC2 合规格式）

**商业漏斗**：开发者免费使用 → 团队规模超过 10 人后转为付费商业版（HITL 节点 + 高级审计 + 预设包）

#### SOC2 认证套件（文档）

帮助客户通过 SOC2 AI Coding 审查，直接提供：
- 《SOC2 AI Coding 审计准备 Checklist》
- AuditLog 导出模板（SOC2 审计员直接审阅格式）
- KodeForge 自身的 SOC2 控制点映射矩阵

### 5.3 定价探索

```
Free        → 个人/5人以下：基础 Quality Gate，无 HITL，无审计导出
Team $49/人月 → 10-50人团队：HITL 节点 + AuditLog + 金融预设
Enterprise    → 50+人：私有化部署 + SOC2套件 + SLA + 专属支持
```

> 定价是探索性的，以客户对话验证后调整，先收钱再精细化。

### 5.4 阶段性指标（Q4 末）

| 指标 | 达成标准 |
|------|---------|
| GitHub Action | 发布 v1，App Store 可安装 |
| 商业版 Closed Beta | ≥ 5 个团队试用 |
| 付费客户 | ≥ 2 个（Phase 1 种子客户升级 + 新客户） |
| 月收入 (MRR) | ≥ 2 万元 |
| 白皮书下载 | ≥ 500 次 |
| 社区 | 公众号关注 ≥ 1000，技术文章持续输出 |

---

## 六、Phase 3（2027 H1）：规模化

### 6.1 目标
- KodeForge 从项目变成产品：发布商业版 v1.0
- 月收入 (MRR)：≥ 10万元
- 客户数：≥ 10 个付费团队

### 6.2 关键动作

#### 产品侧

**v1.0 商业版功能加码**：
- **Slack/钉钉审批集成**：HITL 节点直接推送审批消息，不用跳到另一个系统
- **AI 归因仪表盘**：哪段代码是哪个模型在什么 prompt 下生成的，一目了然
- **团队质量趋势图**：随时间追踪 Quality Score 变化，是 AI 代码质量治理的度量基线
- **合规报告一键导出**：自动生成 SOC2/HIPAA/等保 合规报告 PDF

#### 商业化侧

**三种获客渠道并行**：

**渠道 1：内容营销（建立话语权）**
- 月度技术通讯（Newsletter）：AI Coding 合规动态 + KodeForge 案例
- 季度报告：《企业 AI Coding 合规指数》（调研数据 + 行业基准）
- 年度大会/闭门会议：邀请 CISO/CTO，KodeForge 作为主办方之一

**渠道 2：渠道合作**
- 等保测评机构合作：KodeForge 作为等保2.0 AI Coding 合规的推荐工具
- 安全咨询公司合作：作为 SOC2 审计的配套工具包
- 系统集成商合作：集成到金融/政务的完整解决方案中

**渠道 3：产品驱动增长（PLG）**
- GitHub Action 是持续获客的引擎（开发者免费使用 → 团队转化）
- 开源核心 + 商业版的双轨策略

### 6.3 阶段性指标（2027 H1 末）

| 指标 | 达成标准 |
|------|---------|
| 产品 | v1.0 商业版 GA |
| 月收入 (MRR) | ≥ 10 万 |
| 付费团队数 | ≥ 10 个 |
| 重点行业标杆客户 | ≥ 1 个头部客户（如城商行/大型金融科技） |
| 渠道合作伙伴 | ≥ 3 个（安全咨询/等保测评/集成商） |
| 团队规模 | 扩充至 5-8 人（产品+销售+工程） |
| 内容资产 | 1 份年度白皮书 + 季度合规报告 + 持续 Newsletter |

---

## 七、商业模式汇总

```
                个人开发者          成长型企业          大型金融/政务
             ──────────────    ──────────────    ──────────────
产品           开源免费版          Team 商业版         Enterprise
定价            $0                $49/人月            自定义（10万+/年）
部署            本地 SaaS           SaaS 或混合         私有化
支持            社区               邮件                 专属客户成功经理
核心卖点        质量门禁            HITL+审计追踪        完整合规套件+认证
                                                              + SLA
```

**营收路径**

```
2026 Q3     2026 Q4      2027 Q1-Q2     2027 H2
  种子POC  →  MRR 2万   →  MRR 10万   →  MRR 30万
  验证需求      PLG 驱动      渠道合作      垂直扩展
              Action GA    白皮书营销    医疗/政务
```

---

## 八、风险全景与对冲

| # | 风险 | 概率 | 影响 | 触发信号 | 对冲策略 |
|---|------|------|------|---------|---------|
| R1 | Schema-first 劝退开发者 | **高** | 高 | Action 安装后 7 日留存 < 5% | Phase 1 主推合规（schema 是附带），Phase 2 提供自然语言→Schema 转换向导 |
| R2 | 金融客户决策周期长 | **高** | 高 | 6个月未出首单 | 同时推进金融科技创业公司（决策快）；打 SOC2 审核点（刚性时间约束） |
| R3 | Snyk+Qodo 合并体快速蚕食 | 中 | 高 | 对方发布"AI Compliance"功能 | 强化 HITL+审计一体化（单点工具做不到）；绑定垂直行业合规标准 |
| R4 | CodeRabbit 扩展到质量门禁 | 中 | 中 | 对方融资公告含类似路线图 | 我们是"管线生成+质量+审批"一体化，CodeRabbit 是 PR 工具，赛道不同 |
| R5 | 独立开发者不愿为工具付费 | **高** | 中 | Action 安装量高但转化低 | 个人版永久免费；靠企业合规刚需付费 |
| R6 | 现有 1095 测试在新包拆分中破坏 | 中 | 中 | CI 持续红线 | 先完整镜像再迁移；使用 tox 矩阵保证兼容 |
| R7 | 竞品（Dify/Cursor）推出企业级合规版 | 低 | 高 | 对方企业版发布 | 速度是护城河：比大厂早 12 个月切入金融/医疗垂直合规 |

---

## 九、竞品动态持续追踪清单

每周竞品侦察，填入此表：

| 竞品 | 最新动态（版本/功能/融资） | 对 KodeForge 的威胁等级 | 应对 |
|------|------------------------|----------------------|------|
| CodeRabbit | — | 中 | — |
| Snyk + Qodo | 2025年合并，应关注 v1 产品 | 高 | — |
| Augment Code | — | 低 | — |
| Qodo (CodiumAI) | — | 中 | — |
| GitClear | — | 低 | — |
| AuditAI | — | 低 | — |
| Cursor (Enterprise) | — | 低 | — |

---

## 十、立即开始的一周行动（本周）

```
周一  │ 确认 kodeforge-quality 包的依赖清单，建立 packages/ 骨架
周二  │ 起草金融合规白皮书大纲（2小时），发 1 篇 LinkedIn/脉脉 钩子文
周三  │ 完成 3 个金融预设配置文件草稿（general/sox/tier3）
周四  │ 发布首篇公众号/公众号/Zhihu 技术长文
周五  │ 列出 20 个潜在种子客户脉脉名单，发个性化触达邮件
```

---

*文档路径：`D:\IDLE\Kode-Forge\project\KodeForge\docs\PATH_A_发展路径.md`*
*下一步评审点：2026-08-01（季度中评估）*
