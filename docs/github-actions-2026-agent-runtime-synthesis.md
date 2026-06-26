# GitHub Actions 正在从 CI 流水线进化为 Agent 运行时——2026 是分水岭

## 核心观点

GitHub Actions 的架构长期被一个核心约束定义：steps 严格串行、runner 只做执行、调度全部在服务端。2026 年的 background steps 改动打破了这个约束，而打破它的时机并非偶然——Copilot coding agent 此刻正以 Actions 为执行底座大规模铺开。这不是两个独立事件，而是同一个转变的两面：Actions 正在从"跑测试的流水线"变成"跑 agent 的运行时"，而 background steps 正是让 runner 能承载 agent 并发执行需求的架构基石。

## 技术分析

### 把调度留在服务端，让 runner 保持"愚蠢"——这是 Actions 能扩展到千万级日活的根基

**发生了什么**: Actions 的 DAG 编排和作业调度全部在服务端的 Actions Service 完成，runner 只是执行一个已调度好的 job 之步骤的远程进程。runner 运行时是两个协作进程：listener（父进程，持有 RSA 私钥，长轮询 per-runner 消息队列）和 worker（子进程，执行单个 job）。每个 step 作为独立子进程运行。
- 来源：[actions/runner auth.md 设计文档](https://github.com/actions/runner/blob/main/docs/design/auth.md)（Tier-1）、[contribute.md](https://github.com/actions/runner/blob/main/docs/contribute.md)（Tier-1，明确"workflows and orchestrations run service side with the runner being a remote process"）

**为什么重要**: 这种"聪明在服务端、愚蠢在 runner"的分工是 Actions 可扩展性的根本。runner 不需要理解工作流拓扑、不需要知道 job 之间的依赖——它只管拉取一个 job 消息然后执行其 steps。这意味着 runner 可以是无状态的、可大规模复制的、可丢弃的。如果调度逻辑在 runner 端，每个 runner 都要维护全局视图，扩展性会立刻崩塌。这个设计直接继承自 Azure Pipelines Agent，是被验证过的架构。job 之间的 DAG 边（`needs`）声明在 YAML 里，服务端负责拓扑排序和失败级联（下游 job 默认跳过），runner 全程不知情。

**影响**: 这意味着开发者写的 `workflow.yaml` 只是声明式的 DAG 描述——你声明 `needs` 和 `concurrency`，服务端负责调度。开发者不需要写任何调度代码，也不需要在 runner 端维护状态。这是 GitHub 能用同一套 runner 二进制支撑海量 job 的前提。

> Confidence: High — 多个 Tier-1 第一方源（runner 设计文档 auth.md、contribute.md）一致描述 listener→worker→subprocess 模型和服务端调度，且与 workflow 语法文档（job 默认并行、needs 串行、失败级联）互相印证，无反对证据。

### 临时 VM + 单次令牌：安全模型不是附加层，而是架构决定

**发生了什么**: GitHub-hosted runner 对每个 job 启动一个全新的、隔离的、临时的 VM。每个 job 的 OAuth 令牌按 run 作用域签发，用 runner 公钥加密，从不持久化，并从日志中擦除。hosted runner 从 `.credentials` 获取一次性令牌，job 结束即吊销；self-hosted runner 用 RSA 密钥对注册。而 self-hosted runner 没有这些临时性保证——不可信 PR 代码可以持久性攻陷它们。
- 来源：[安全加固指南](https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions)（Tier-1，明确"ephemeral and clean isolated virtual machines"与 self-hosted 可被持久性攻陷）、[auth.md](https://github.com/actions/runner/blob/main/docs/design/auth.md)（Tier-1，令牌机制）、[about-github-hosted-runners](https://docs.github.com/en/actions/using-github-hosted-runners/about-github-hosted-runners)（Tier-1，每个 hosted runner是新 VM，Azure Pipelines Agent 分支）

**为什么重要**: 这解决的是"不可信代码执行"这个根本信任问题。在 CI 系统里，你执行的代码来自外部贡献者（PR），这是默认不可信的。临时 VM 的意义不是"干净"，而是"不可能持久化攻陷"——攻击者在一个 job 里拿到 root，VM 销毁后一切归零。单次令牌和日志擦除堵住了凭据泄露的侧信道。这是为什么 GitHub-hosted runner 可以安全地跑公开仓库的 PR，而 self-hosted runner 不行——这不是配置差异，是架构差异。

**影响**: 这意味着开发者可以放心让外部贡献者的 PR 触发完整 CI 而不担心供应链攻陷（在 hosted runner 上）。而 self-hosted runner 的安全缺口是真实的、被官方文档明确警告的——任何把 self-hosted runner 暴露给 fork PR 的团队都在承担持久化攻陷风险。

> Confidence: High — 官方安全加固指南明确表述临时隔离 VM 和 self-hosted 持久化攻陷风险，与 auth.md 的令牌机制和 about-hosted-runners 的 VM 模型互相印证。

### background steps：2026 年最重要的 runner 架构变更，因为它打破了定义 Actions 的那条约束

**发生了什么**: 2026-06-25 GitHub 宣布 "Actions steps can now be run in parallel"。runner v2.335.0（2026-06-08）落地 background steps，新增四个关键词：`background: true`、`wait`/`wait-all`、`cancel`、`parallel`。此前 steps 严格串行；此前想并发只能用 shell 后台化（`&`），但日志会交错混乱。核心实现在 [PR #4476](https://github.com/actions/runner/pull/4476) 的 `BackgroundStepCoordinator.cs`：并发信号量（默认上限 10），且并发控制在 runner 端而非服务端；前台 step 即使后台槽位满也能继续（非阻塞信号量）；post-hooks 前隐式 `wait-all` 作为安全网。
- 来源：[changelog 官宣](https://github.blog/changelog/2026-06-25-actions-steps-can-now-be-run-in-parallel/)（Tier-1）、[PR #4476](https://github.com/actions/runner/pull/4476)（Tier-1）、[v2.335.0 release](https://github.com/actions/runner/releases/tag/v2.335.0)（Tier-1）

**为什么重要**: 这是理解整个 2026 叙事的关键。steps 严格串行不是一个 bug，而是一个刻意的约束——串行保证了状态隔离：每个 step 顺序写 `GITHUB_OUTPUT`/`GITHUB_ENV`/`GITHUB_PATH`，不会互相覆盖。background steps 不是简单地"加并发"，而是要同时拿到并发能力和状态隔离保证。它用的是 **defer-and-flush 模型**：后台 step 的环境变量/输出写入先缓冲，在 `wait` 时由主线程刷写。被 `cancel` 的后台 step 不会让 job 失败（但失败的会）。这说明团队清楚地知道自己在放松哪个约束、用什么机制补偿。

同时，一个微妙的权力转移发生了：并发控制从服务端移到了 runner 端——runner 第一次拥有了"自己的"并发语义。在此之前 runner 只是执行一条 step 序列的 dumb pipe；现在 runner 自己管理一个并发信号量。这是 runner 从"愚蠢执行器"向"有局部智能的运行时"的转折点。

**影响**: 这直接解锁三类此前做不好或做不了的场景：(1) 并行构建——多平台编译同时跑，CI 时间线性下降；(2) 启动-停止模式——起一个后台服务（数据库、mock server）跑测试然后关掉，日志不再交错；(3) 非阻塞遥测上传——测试跑着的同时上传覆盖率，不再串行等待。对开发者生产力的直接影响是 CI 总时间下降，尤其是大型 monorepo 的构建流水线。

> Confidence: High — 全部基于 Tier-1 源（GitHub changelog、runner 源码 PR、release notes），BackgroundStepCoordinator 的非阻塞信号量与 defer-and-flush 状态模型可直接在 PR #4476/#4472/#4475/#4479/#4482 中验证。

### Copilot coding agent 跑在 Actions 上——这就是 background steps 为什么现在出现

**发生了什么**: Copilot coding agent（2025-05-19 公开预览）的工作方式是：把 GitHub Issue 分配给 Copilot，它在"由 GitHub Actions 驱动的安全云开发环境"中工作，跑测试验证后才推送。2026-06-04 Agent Tasks REST API 上线，Copilot Pro/Pro+/Max 可以编程式地启动和追踪云 agent 任务——支持跨仓库 fan-out 重构、一键仓库初始化、自动准备每周发布。2026-06-17 Agent finder 上线，agent 能自主发现合适的技能；2025-12-18 Agent Skills 上线，Copilot 自动加载相关指令/脚本。
- 来源：[coding agent 预览](https://github.blog/changelog/2025-05-19-github-copilot-coding-agent-in-public-preview/)（Tier-1）、[Agent Tasks API](https://github.blog/changelog/2026-06-04-agent-tasks-rest-api-now-available-for-copilot-pro-pro-and-max/)（Tier-1）、[Agent finder](https://github.blog/changelog/2026-06-17-agent-finder-for-github-copilot-now-available/)（Tier-1）、[Agent Skills](https://github.blog/changelog/2025-12-18-github-copilot-now-supports-agent-skills/)（Tier-1）

**为什么重要**: 把这两件事放在一起看：Copilot coding agent 的执行底座就是 Actions。而 agent 的工作模式天然需要并发——agent 要一边编译、一边跑测试、一边上传遥测、一边维护后台服务。一个严格串行 step 的流水线是糟糕的 agent 运行时。background steps 的 changelog 列出的用例（后台服务、非阻塞遥测、并行构建）几乎就是 agent 执行场景的清单。时间线也高度吻合：Agent Tasks API（6 月 4 日）→ background steps 落地（6 月 8 日 v2.335.0）→ background steps 官宣（6 月 25 日）。这强烈暗示 background steps 不是为传统 CI 用户做的功能，而是为让 runner 成为合格的 agent 运行时而做的架构升级。

**影响**: 这意味着 GitHub 的赌注很清楚——Actions 不只是 CI/CD 工具，它是 GitHub 整个 AI agent 战略的执行层。开发者通过 Agent Tasks API 批量派发 agent 任务，底层跑在已具备并发能力的 runner 上。这把"写 workflow.yaml 跑测试"和"派 agent 改代码"统一到了同一个运行时——开发者面对的是同一套执行基础设施，只是上层从声明式 pipeline 变成了 agentic task。

> Confidence: High（事实）/ Medium（因果推断）— agent 跑在 Actions 上、background steps 的用例与 agent 场景重合、时间线吻合都是 High 置信的 Tier-1 事实；"background steps 专为 agent 而做"是合理的因果推断，GitHub 未官方声明此因果关系，但证据链强。

### Agent 的攻击面也随之打开——prompt injection 是 agent-on-Actions 的新风险层

**发生了什么**: Trail of Bits 演示了针对 Copilot coding agent 的 prompt injection 攻击：攻击者提交带隐藏注入的 issue，Copilot 在生成的 PR 中插入后门。利用的是 agent 上下文松散结构化（XML 标签），agent 无法区分合法 XML 与注入 XML；还用 HTML `picture`/`source` 标签隐藏注入。报告预测随 agent 采纳率上升影响会扩大。
- 来源：[Trail of Bits](https://blog.trailofbits.com/2025/08/06/prompt-injection-engineering-for-attackers-exploiting-github-copilot/)（Tier-2）

**为什么重要**: 这把前面两个安全分析连起来了。GitHub-hosted runner 的临时 VM 模型解决了"不可信代码执行"的**操作系统层**攻陷——VM 销毁即归零。但 agent 引入了一个新的、runner 安全模型覆盖不到的层：**语义层**攻陷。攻击者不需要攻陷 VM，只需要让 agent 在合法的执行环境里"自愿地"产出恶意代码并提交 PR。临时 VM 防不住这个，因为攻击发生在 agent 的推理过程里，不在 runner 的进程隔离里。background steps 让 agent 能并发执行更多操作，也意味着一个被注入的 agent 能同时在更多地方埋下后门。

**影响**: 这意味着当团队开始用 Agent Tasks API 批量派发跨仓库 agent 重构时，prompt injection 从"单 PR 恶作剧"升级为"跨仓库供应链风险"。代码审查不能因为"agent 跑过测试"就跳过——agent 跑的测试可能是 agent 自己写的。

> Confidence: Medium — 单一 Tier-2 源（Trail of Bits，reputable 安全公司但属博客分析），攻击可行性有具体演示但样本有限；影响随采纳率扩大的判断是合理推断。

## 直接回答

你想写一篇把 GitHub Actions 技术讲透的博客，并结合 2026 agent 趋势和代码仓改动。我的判断是：**这篇博客的真正主线不是"GitHub Actions 怎么工作"，而是"GitHub Actions 正在从 CI 流水线变成 agent 运行时，而 2026 年的代码仓改动是这场转变的架构证据"。**

博客应该这样组织叙事：

1. **先讲架构地基**：服务端 DAG 调度 + 愚蠢的远程 runner + 临时 VM 安全模型。这是为什么 Actions 能扩展、能安全跑不可信代码。这是"为什么之前能做到"的部分。
2. **再讲 2026 的破局点**：background steps 打破了 steps 严格串行这个定义性约束，但用 defer-and-flush 模型保留了状态隔离。注意并发控制从服务端移到 runner 端这个权力转移——这是 runner 进化的信号。
3. **然后讲 agent 趋势如何使这个破局点变得必然**：Copilot coding agent 跑在 Actions 上，agent 天然需要并发，Agent Tasks API 让批量派发成为可能。background steps 的用例清单和时间线强烈指向"为 agent 而做"。
4. **最后讲新风险层**：agent-on-Actions 引入了 runner 安全模型覆盖不到的语义层 prompt injection 风险。

这个叙事的好处是它有因果链：架构地基（串行+隔离）→ 约束被打破（background steps）→ 为什么现在打破（agent 需要并发）→ 新风险（prompt injection）。读者看完能理解"为什么 2026 是分水岭"，而不是看到一堆平行的事实。

代码仓改动方面，重点剖析 `actions/runner` 的 background steps PR 栈（#4472 → #4475 → #4479 → #4476 → #4482），尤其 `BackgroundStepCoordinator.cs` 的非阻塞信号量和 defer-and-flush 状态模型——这是最能体现"精心放松约束"的工程细节，值得博客深挖。v2.335.0 还捆绑了 DAP 调试器、Ubuntu 26.04、Node 24、SHA-256，可一并提及。

## 信号强度说明

**强证据支撑的观点**：架构模型（服务端调度 + 愚蠢 runner + listener/worker 双进程）、临时 VM 安全模型与 self-hosted 风险、background steps 的技术实现（PR 栈、并发信号量、defer-and-flush）、Copilot coding agent 跑在 Actions 上、Agent Tasks API 的能力——这些都有多个 Tier-1 源（官方设计文档、源码 PR、GitHub changelog）交叉印证，可作为博客的事实骨架。

**推断性观点（合理但非官方确认）**：background steps 专为 agent 运行时而做的因果判断。证据链强（用例重合 + 时间线吻合 + agent 跑在 Actions 上），但 GitHub 未官方声明此因果关系。博客中应表述为"强烈暗示"而非"官方确认"。

**需谨慎的事实**：7100 万日活 job、hosted runner 降价 39%、self-hosted 自 2026 年 3 月起收费、缓存 10GB 上限移除等运营数据来自单一 Tier-2 源（webhani 博客），且 self-hosted 收费存在 Tier-2 反对源（称已无限期推迟）。博客引用这些数据时应标注来源级别，或仅作为背景而非论证支柱。

## Sources Consulted

- https://github.com/actions/runner/blob/main/docs/design/auth.md — Tier 1 — Runner 认证设计文档：RSA 密钥对、per-runner 消息队列、HTTP 长轮询、per-job 作用域令牌、listener→worker→subprocess 模型
- https://github.com/actions/runner/blob/main/docs/contribute.md — Tier 1 — "工作流和编排在服务端运行，runner 是执行 steps 的远程进程"；listener+worker 双进程模型
- https://docs.github.com/en/actions/using-github-hosted-runners/about-github-hosted-runners — Tier 1 — 每个 hosted runner 是新 VM；Azure Pipelines Agent 分支；VM 规格
- https://docs.github.com/en/actions/using-workflows/about-workflows — Tier 1 — Trigger→run 生命周期
- https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions — Tier 1 — job 默认并行、needs 串行、失败级联
- https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions — Tier 1 — 临时隔离 VM；self-hosted 可被不可信代码持久性攻陷
- https://github.blog/changelog/2025-05-19-github-copilot-coding-agent-in-public-preview/ — Tier 1 — Copilot coding agent 公开预览，跑在 Actions 驱动的云开发环境
- https://github.blog/news-insights/product-news/github-copilot-the-agent-awakens/ — Tier 1 — agent mode in VS Code，自愈循环，多模型
- https://github.blog/changelog/2026-06-04-agent-tasks-rest-api-now-available-for-copilot-pro-pro-and-max/ — Tier 1 — Agent Tasks REST API，编程式启动追踪 agent 任务，跨仓库 fan-out
- https://github.blog/changelog/2025-12-18-github-copilot-now-supports-agent-skills/ — Tier 1 — Agent Skills，自动加载指令/脚本
- https://github.blog/ai-and-ml/github-copilot/evaluating-performance-and-efficiency-of-the-github-copilot-agentic-harness-across-models-and-tasks/ — Tier 1 — Copilot agentic harness 基准，SWE-bench，20+ 模型
- https://github.blog/changelog/2026-06-17-agent-finder-for-github-copilot-now-available/ — Tier 1 — Agent finder + 开放 ARD 规范
- https://github.blog/changelog/2026-06-25-actions-steps-can-now-be-run-in-parallel/ — Tier 1 — background steps 官宣，四个新关键词
- https://github.com/actions/runner/pull/4476 — Tier 1 — BackgroundStepCoordinator.cs，并发信号量默认 10，runner 端并发控制，非阻塞，隐式 wait-all
- https://github.com/actions/runner/releases/tag/v2.335.0 — Tier 1 — v2.335.0 release，bundling background steps + DAP debugger + Ubuntu 26.04 + Node 24
- https://www.webhani.com/blog/github-actions-2026-cicd-evolution — Tier 2 — 71M jobs/day，2025 后端重构，hosted 降价，self-hosted 收费，缓存上限移除
- https://dev.to/dataformathub/github-actions-2026-why-the-new-runner-scale-set-changes-everything-4kbi — Tier 2 — runner scale-set Go 客户端，self-hosted 收费争议（已推迟）
- https://blog.trailofbits.com/2025/08/06/prompt-injection-engineering-for-attackers-exploiting-github-copilot/ — Tier 2 — Copilot coding agent prompt injection 攻击演示
