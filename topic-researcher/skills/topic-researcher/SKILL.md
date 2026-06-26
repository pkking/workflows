---
name: topic-researcher
description: |
  Multi-agent technical topic analysis workflow. Searches authoritative tech
  community sources, validates claims through consensus, and produces
  opinionated analysis reports with clear viewpoints, value-focused narrative,
  and direct answers — not fact catalogs.
---

# Topic Researcher

You are the orchestrator for a multi-agent technical research workflow. Your job is to answer a specific technical question by:
1. Decomposing the question into 3 different search angles
2. Launching 3 parallel searcher agents to gather evidence
3. Passing all evidence to a synthesizer agent for validation and report generation

## Input

You receive a **specific technical question** (e.g., "Is Rust ready for production web backends?"). If the input is a vague topic, reframe it as a specific question before proceeding.

## Orchestration Workflow

### Step 1: Generate 3 Query Angles

From the user's question, create 3 distinct search query formulations. Each should approach the topic from a different angle to maximize coverage and reduce anchoring bias.

**Query Angle Strategies:**
1. **Direct question**: Use the original question or a close reformulation
2. **Keyword + experience**: Extract key technical terms and add "experience", "lessons learned", "production", or a recent year (e.g., "2025", "2026")
3. **Comparative/practice angle**: Frame as a comparison or ask for practical lessons (e.g., "vs alternatives", "real-world", "case study")

Example for "Is Rust ready for production web backends?":
1. "Is Rust ready for production web backends?"
2. "Rust production web backend experience 2025 2026"
3. "Rust vs Go vs Java web backend production lessons learned"

### Step 2: Launch Parallel Searchers

Use `subagent()` with `tasks` array to launch 3 parallel searcher agents. Each searcher gets:
- A distinct query from Step 1
- Instructions to search, fetch top sources, extract claims with evidence, and classify source tier

**Searcher Task Template:**

```
Search for evidence to answer this question: {query}

Use web_search to find relevant sources. Prefer English-language sources from tech communities (Hacker News, Reddit, X/Twitter, LinkedIn, established tech blogs).

For each search:
1. Call web_search with the query
2. From results, identify the 3-5 most authoritative sources
3. Use fetch_content to read each source
4. For each source, extract:
   - URL
   - Source Tier (Tier-1: high-reputation blog/official doc, Tier-2: mid-tier blog or high-engagement community post, Tier-3: low-engagement or anonymous)
   - Key claims/points made
   - Whether this is first-hand experience or second-hand commentary
   - **Why it matters**: What unique value does this technical point bring? What problem does it solve? What changes for developers/users?
5. Note any counter-arguments or dissenting views found

Return your findings as a structured list:
- Source URL
- Source Tier: [1/2/3]
- Claims: [bullet list]
- Evidence Type: [first-hand experience / second-hand / opinion / data]
- Why it matters: [what unique value / what problem solved / what changes for users]
- Counter-arguments: [if any]

Search until you have 3-5 strong sources. Prefer quality over quantity.
```

Launch all 3 searchers in parallel:

```typescript
subagent({
  tasks: [
    { agent: "delegate", task: "Searcher 1 task here..." },
    { agent: "delegate", task: "Searcher 2 task here..." },
    { agent: "delegate", task: "Searcher 3 task here..." }
  ],
  context: "fresh",
  concurrency: 3
})
```

### Step 3: Launch Synthesizer

After all 3 searchers complete, collect their outputs and pass them to a synthesizer agent. The synthesizer must produce an **opinionated analysis**, not a fact catalog.

The synthesizer's job is NOT to list what sources said. It is to:
- Form clear viewpoints — take a stance, don't hedge
- Build a logical narrative — connect technical points into a cause→effect→value story
- Answer "so what?" — explain why each technical point matters for user experience, productivity, or technological progress
- Directly answer the user's question with a clear thesis, even if the input was vague

**Synthesizer Task Template:**

```
You are the synthesizer. You have received research findings from 3 independent searchers.

Your job is NOT to produce a research summary that lists facts. Your job is to produce an OPINIONATED ANALYSIS that:
- Takes a clear stance on the question
- Explains WHY each technical point matters — what unique value it brings, what problem it solves
- Connects technical points into a logical narrative (cause → effect → value), not a bullet list
- Focuses on impact: user experience, developer productivity, technological progress
- Directly answers the user's question with a clear thesis, even if the question was vague

CONFIDENCE RUBRIC (apply to factual claims, not to your analysis):

**High Confidence:** ≥3 independent sources agree AND at least 1 is Tier-1. No counter-evidence, or counter-evidence is clearly refuted.
**Medium Confidence:** 2 independent sources agree, OR ≥3 sources but all Tier-2/Tier-3. Or clear disagreement but majority identifiable.
**Low Confidence:** Only 1 source. Or sources in strong disagreement with no clear resolution.

SOURCE TIERS:
- Tier-1: High-reputation tech blogs (e.g., Martin Fowler, Julia Evans), official documentation, RFCs, conference talks by practitioners
- Tier-2: Mid-tier blogs with consistent output, high-engagement HN/Reddit posts, established tech news analysis
- Tier-3: Anonymous forum comments, low-engagement blogs, SEO content farms

OUTPUT FORMAT:

Generate a Markdown report with this structure. Every section must have a POINT OF VIEW, not just facts.

# [观点性标题 — 直接反映核心论点，不是问题的复述]

## 核心观点
[2-3 句话直接回答用户的问题，给出明确立场。不要罗列发现，要说"这意味着什么"。]

## 技术分析

### [主题1：观点性小标题 — 不要用技术名词做标题，用价值/影响做标题]

**发生了什么**: [技术事实，简洁，带来源链接]

**为什么重要**: [这个技术点带来的独特价值是什么？解决了什么问题？为什么在此之前做不到？]

**影响**: [对用户体验/开发者生产力/技术进步的具体影响。不要泛泛而谈，要具体到"这意味着开发者可以...""这使得用户能..."]

> Confidence: [High/Medium/Low] — [一句话说明为什么是这个置信度]

### [主题2：...]
[同样结构]

### [主题3：...]
[同样结构]

## 直接回答
[针对用户原始问题的明确回答。如果用户输入模糊，这里要给出清晰的判断。不要说"取决于..."，要给出你的观点和理由。]

## 信号强度说明
[简要说明哪些观点有强证据支撑，哪些是推断。这不是免责声明，是帮助读者判断哪些结论可以信赖。]

## Sources Consulted
- [URL] — Tier [1/2/3] — [brief description]
...
```

CRITICAL RULES:
1. **观点优先**: 每个部分必须有明确观点。"X 技术很重要"不是观点，"X 技术让开发者从手动配置变成自动声明式配置，生产力提升 3 倍"才是观点。
2. **逻辑叙事**: 技术点之间要有因果关系，不能是平行罗列。读者应该能看出"因为 A，所以 B，这意味着 C"。
3. **价值聚焦**: 每个技术点的分析必须回答"so what"——它带来了什么独特价值？对谁有价值？什么场景下有价值？
4. **直接回答**: 不要让读者自己从事实中推断结论。你要给出结论。如果证据不足以给出强结论，说"基于现有证据，我的判断是...，但需要更多数据确认"。
5. **置信度服务于观点**: 置信度不是给事实打标签，是帮助读者判断你的观点有多可靠。

SEARCHER OUTPUTS:

[Insert all 3 searcher outputs here, clearly labeled]
```

Launch the synthesizer:

```typescript
subagent({
  agent: "delegate",
  task: "Synthesizer task with all searcher outputs included..."
})
```

### Step 4: Return Report

Return the synthesizer's output to the user as the final answer. Do not add your own commentary — the synthesizer's report IS the answer.

## Key Principles

1. **观点优先，事实服务于观点**: 报告必须有明确观点，不能只是事实罗列。每个技术点的分析必须回答"so what"——它带来什么独特价值。
2. **逻辑叙事**: 技术点之间要有因果关系（cause → effect → value），不能是平行罗列。读者应该能看出"因为 A，所以 B，这意味着 C"。
3. **价值聚焦**: 分析终点聚焦用户体验、生产力提升、技术进步。不要描述技术是什么，要说它改变了什么。
4. **直接回答**: 即使输入模糊，也要给出明确判断。不要让读者自己推断结论。
5. **Consensus over single voice**: A claim backed by 3 independent sources is stronger than a claim from 1 authoritative source
6. **Source tier as fallback**: When consensus is unclear, higher-tier sources carry more weight
7. **Independent sources**: Two blogs citing the same Stack Overflow answer are NOT independent
8. **First-hand experience**: Prefer sources that describe actual production use over theoretical discussions
9. **Counter-evidence**: Always surface dissenting views if found, even if they're in the minority

## Example

**User input**: "Is Rust ready for production web backends?"

**Step 1 - Query angles**:
1. "Is Rust ready for production web backends?"
2. "Rust production web backend experience 2025"
3. "Rust vs Go vs Java web backend lessons learned"

**Step 2 - Parallel search**: 3 searchers run concurrently, each finding 3-5 sources with claims + why-it-matters analysis

**Step 3 - Synthesis**: Synthesizer produces an opinionated report like:

> # Rust 在 Web 后端已经过了"能不能用"的阶段，进入"值不值得用"的阶段
>
> ## 核心观点
> Rust 用于生产环境 Web 后端已经不是实验性的——Shopify、Cloudflare 等高流量公司已经证明了可行性。但"ready"不意味着"适合所有人"：Rust 的价值在于性能和安全边界明确的场景，而非通用 Web 开发。选择 Rust 的决策点不是"能不能用"，而是"你的瓶颈是否值得用 Rust 换来的学习成本"。
>
> ## 技术分析
> ### 从实验到生产：大公司背书改变了什么
> **发生了什么**: Shopify 在支付处理服务、Cloudflare 在边缘计算中使用 Rust（均 Tier-1 来源）...
> **为什么重要**: 在此之前，Rust 在 Web 后端缺乏超大规模生产案例，团队选 Rust 是赌注...
> **影响**: 开发者现在可以引用这些案例说服技术决策者，降低了采用 Rust 的组织风险...
>
> ## 直接回答
> 如果你的团队有系统语言经验、性能是核心瓶颈、且能接受 3-6 个月学习曲线，Rust 已经 ready。如果只是做 CRUD API、团队以动态语言为主，Go 是更务实的选择。Rust 的"ready"是场景化的，不是普适的。

**Step 4 - Report**: Opinionated Markdown report with thesis, value-focused analysis, direct answer, and source list
