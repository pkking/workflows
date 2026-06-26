# Topic Researcher

多 agent 技术问题分析工作流。通过搜索权威技术社区信源、基于共识验证观点、生成带置信度评分的报告来回答特定技术问题。

## 功能特点

- **多 agent 并行搜索**：3 个独立的搜索 agent 从不同角度搜索，减少锚定偏差
- **共识驱动**：基于多个独立来源的一致性来判定置信度
- **权威信源优先**：优先选择英文技术社区（Hacker News、Reddit、X/Twitter、LinkedIn、知名技术博客）
- **结构化报告**：输出带有置信度评分（High/Medium/Low）和完整引用来源的 Markdown 报告
- **可复用工作流**：作为 pi skill 打包，可在任何项目中使用

## 安装

### 方式 1：本地安装（开发模式）

```bash
# 在 workflows 目录下
pi install ./topic-researcher
```

### 方式 2：项目级安装

```bash
# 在目标项目目录下
pi install -l ./topic-researcher
```

### 方式 3：临时使用（不安装）

```bash
pi -e ./topic-researcher
```

## 使用

安装后，在 pi 中使用 `/topic-research` 命令：

```
/topic-research Is Rust ready for production web backends?
```

或者：

```
/topic-research 微服务架构在什么规模下开始变得必要？
```

## 工作流程

### 1. 问题分解

Skill 会将你的技术问题分解为 3 个不同角度的搜索查询：
- **直接提问**：原始问题的重新表述
- **关键词 + 经验**：提取技术关键词，加上 "experience"、"lessons learned" 等
- **对比/实践角度**：框架为对比或实际案例

### 2. 并行搜索

同时启动 3 个搜索 agent，每个 agent：
- 使用不同的查询角度搜索
- 抓取 top 3-5 个权威来源
- 提取关键观点、来源层级、证据类型
- 记录反面观点

### 3. 综合分析

合成 agent 接收所有搜索结果，执行：
- **交叉验证**：识别多个独立来源的共同观点
- **共识评估**：统计每个观点的独立支持来源数量
- **置信度判定**：应用置信度 rubric
- **报告生成**：生成结构化的 Markdown 报告

## 置信度 Rubric

### High（高置信度）
- ≥3 个独立来源一致，且至少 1 个是 Tier-1
- 无反面证据，或反面证据被明确驳斥

### Medium（中置信度）
- 2 个独立来源一致，或 ≥3 个来源但都是 Tier-2/Tier-3
- 或存在明显分歧但多数倾向可识别

### Low（低置信度）
- 仅 1 个来源支持
- 或来源间严重分歧且无法判定哪方更可信

## 来源层级

### Tier-1（高信誉）
- 知名技术博客（如 Martin Fowler、Julia Evans）
- 官方文档、RFC、会议演讲
- 有生产经验的一线工程师详细文章

### Tier-2（中等信誉）
- 持续输出的中型技术博客
- 高互动的 HN/Reddit 帖子
- 知名技术媒体的深度分析

### Tier-3（低信誉）
- 匿名论坛评论
- 低互动个人博客
- SEO 内容农场

## 输出示例

```markdown
# Is Rust ready for production web backends?

## Findings

### Rust is production-ready for web backends
- **Confidence**: High
- **Evidence**:
  - https://shopify.engineering/... — Shopify 分享了在支付处理服务中使用 Rust 的经验
  - https://blog.cloudflare.com/... — Cloudflare 描述了 Rust 在高流量边缘服务中的应用
  - https://example.com/... — 另一家公司分享了 2 年生产环境使用 Rust 的经验
  - https://example.com/... — 技术负责人描述了迁移到 Rust 的收益
- **Consensus**: 4 个独立来源一致，包括 2 个 Tier-1 来源
- **Counter-evidence**: None found

### Rust has a steeper learning curve than Go
- **Confidence**: Medium
- **Evidence**:
  - https://example.com/... — 团队负责人表示新人需要 3-6 个月才能达到生产力
  - https://example.com/... — 开发者分享了从 Go 转到 Rust 的学习曲线
  - https://example.com/... — 另一篇文章提到类型系统的复杂性
- **Consensus**: 3 个独立来源一致，但都是 Tier-2 来源
- **Counter-evidence**: None

## Summary

Rust 已被多家公司成功用于生产环境的 web 后端服务，特别是在高性能、高可靠性要求的场景。主要优势包括内存安全、性能和可靠性。主要挑战是学习曲线较陡，团队需要投入时间培训。

## Sources Consulted

- https://shopify.engineering/... — Tier 1 — Shopify 工程博客
- https://blog.cloudflare.com/... — Tier 1 — Cloudflare 技术博客
- ...
```

## 设计决策

这个工作流的设计决策记录在 `docs/decisions/adr-002-topic-researcher-pi-subagent-chain.md`。

核心决策：
- **为什么是 pi skill 而不是 Python 项目**：工作流足够简单，pi 的 subagent 系统原生支持并行和链式调用，不需要自定义 orchestrator 代码
- **为什么是 3 个并行搜索 agent**：最大化搜索覆盖面，减少单一视角的锚定偏差
- **为什么基于共识判定置信度**：技术领域的"真相"经常是从业者共识，不是单一权威论述

## 领域词汇表

领域概念定义在 `CONTEXT.md`，包括：
- 技术问题 vs 宽泛主题
- 高置信度的定义
- 共识的判定标准
- 来源层级分类
- 独立来源的定义
- 一手经验 vs 二手信息

## 开发

### 修改 Skill

编辑 `skills/topic-researcher/SKILL.md` 后，重新安装：

```bash
pi install ./topic-researcher
```

### 测试

在当前目录临时加载（不安装）：

```bash
pi -e ./topic-researcher
# 然后在 pi 中使用 /topic-research
```

## License

MIT
