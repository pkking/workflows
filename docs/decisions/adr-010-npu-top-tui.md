# ADR-010: NPU-Top — 跨集群 NPU 资源 TUI 监控 Skill

**Status**: Proposed
**Date**: 2026-08-14

## Context / 背景

现有仓库有多个面向 Ascend/NPU CI 的分析工具（ci-effective-report、repo-distiller），但缺少一种**实时、跨集群**的 NPU 资源利用率观测手段。运维/CI 同学手头有一个目录（如 `/root/kubeconfig/`），里面散落多份 kubeconfig，每份指向一个固定集群（ascend-ci-prod、ascend-cn12-001、ascend-hk-001 等）。当前只能逐个 `kubectl` 手查，无法一眼看清：

- 各集群 NPU 总量、型号（Ascend910A/B/B2/B3、310P…）分布；
- 当前被 k8s 占用 vs 空闲的比例；
- 排队的 Pod（Pending）数量；
- 异常 Pod（Pending>20min 或 Running>60min，CI 语境下疑似卡死）数量。

需求明确要 **`top` 风格的 TUI、实时刷新、顶部汇总指标**。

## Decision / 决策

新增 skill `npu-top`（`.agents/skills/npu-top/`），由 `SKILL.md` + `scripts/npu_top.py` 组成：

1. **输入**：用户指定一个目录，脚本扫描目录下所有文件，逐个尝试作为 kubeconfig（`kubectl --kubeconfig=<file>`），用 `--request-timeout` 避免不可达集群卡死；可达即采，不可达在结果里标记 `unreachable` 一行带过，不阻断其它集群。

2. **NPU 发现**：从节点 `status.capacity` 识别扩展资源，匹配 `huawei.com/ascend*`（含 ModelArts/CCE 小写 `ascend-1980` 命名）、`huawei.com/Ascend910B`（HAMi 大写命名）、`huawei.com/npu`。型号优先取 node label `node.kubernetes.io/npu.chip.name`（如 `Ascend910`），回退 `accelerator/huawei-npu`、`node-role.kubernetes.io/ascend-*`，再回退资源名。`-memory` 后缀为 vNPU 切片，单独计入 SLICE 列、不重复算物理卡。

3. **占用率**：`occupied = 该节点 pod 的 NPU request 之和`，`occupancy = occupied / capacity`。用 **pod-request 口径**而非 `capacity−allocatable`——实测发现 ModelArts/CCE 设备插件不扣减 allocatable（`capacity==allocatable` 即使有 pod 占用 NPU），`capacity−allocatable` 读 0% 失效。pod-request 是调度可见的真实占用，可能 >100%（超卖/切片）属正常信号。

4. **Pod 分类**（`kubectl get pods -A -o json`）：
   - **排队**：`phase == Pending`（全部 pod，不限于 NPU）。
   - **异常**：只统计**请求了 NPU 资源的 pod**，Pending 且创建至今 >20min；或 Running 且 `startTime` 至今 >60min。排除常驻系统服务（arc-systems self-hosted runner/controller 等运行数天的非 NPU pod），只抓 NPU 工作负载的卡死。阈值（20/60min）取自需求方约定，CLI `--pending-warn` / `--running-warn` 可覆盖。

5. **TUI**：用 stdlib **`curses`** 实现 top 风格界面：顶部汇总区（总 NPU、占用 NPU、占用率%、排队 Pod、异常 Pod，按集群分组）+ 表格区（集群/节点/型号/总/占/空/占用率）。键位：`q` 退出、`r` 立即刷新、`+`/`-` 调间隔、`1`/`2` 切节点/Pod 视图。默认 30s 自动刷新。

6. **非交互入口 `--once`**：打印一次快照为文本表格（无 curses），供 agent/CI/脚本消费；`--mock` 用合成数据走完整逻辑做自检。

## Trade-offs / 权衡

- **纯 stdlib，零依赖**：不引 rich/textual/psutil，用 `curses` + `subprocess(kubectl)` + `json`。好处是无 `uv sync`、无网络、最小 footprint；代价是 curses TUI 需手写布局，无富文本花哨样式。符合 Ponytail「stdlib does it」与「already-installed dependency 之前先看 stdlib」。
- **占用率口径用 pod-request 而非 capacity−allocatable**：实测 ModelArts/CCE 设备插件不扣减 allocatable（`capacity==allocatable` 即使有 pod 占用），`capacity−allocatable` 读 0% 对主流集群失效。改用 pod-request 后实测真实占用率 ~50-60%。代价：可能 >100%（超卖/切片）属正常信号；切片 Pod 只请求 `-memory` 不计入物理 occupied，纯切片集群物理占用率仍低估——`# ponytail: 切片占用未计入物理 occupied，纯切片集群看 SLICE 列`。
- **异常阈值硬编码 CI 语境**：Running>60min 在训练集群会误报（训练动辄数小时）。阈值可 CLI 覆盖，并在 ADR 标明该 skill 默认面向 CI 场景；训练场景请调大 `--running-warn`。
- **每集群两轮 API（nodes + pods）**：跨 N 集群 2N 次 `kubectl`，并发拉取（默认线程池）。刷新间隔默认 30s 足以摊销；高频刷新可 `--interval` 调小但注意 API 压力。
- **kubeconfig 目录扫描全文件**：可能有非 kubeconfig 文件（如 `config.json`、`ghproxy.yaml`），靠 `kubectl` 是否可达过滤，偶发误判。未做内容嗅探（YAML 里有 `kind: Config` 才算），因这会引入 PyYAML 依赖——与零依赖目标冲突，故放弃。

## Alternatives Considered / 备选方案

- **textual/rich 做 TUI**：更美观、更省布局代码，但新增 2 个运行时依赖，违背「fewest deps」；top 风格 curses 足够。放弃。
- **解析 kubeconfig 内联上下文**：可不依赖 kubectl 直接走 HTTP，但 kubeconfig 格式多样（YAML/JSON、多 context、TLS/cert-data/ token/exec），自实现 client 逻辑重且易错；`kubectl` 已成熟、已装，直接复用更稳。放弃。
- **合并多 kubeconfig 为单 `KUBECONFIG=a:b:c`**：一次 `kubectl` 调用拉全部节点，更少子进程。但 context 名常冲突（多个 context 都叫 `default`/`external`），且无法区分某节点属哪份 kubeconfig（集群名丢失）。改为逐文件处理、用文件名做集群标签，虽子进程多但语义清晰。放弃合并方案。
- **Prometheus/metrics-server 取占用率**：更准，但需集群已装 metrics 栈且暴露给本机；多数 CI 集群未必具备。capacity/allocatable 零额外依赖、任何集群都有。放弃。

## Impact / 影响

- 新增 `.agents/skills/npu-top/`（SKILL.md + scripts/npu_top.py + pyproject.toml 零依赖）。
- skill 触发关键字写入 SKILL.md frontmatter `description`，pi 启动时自动扫描命中。
- 不改任何现有子项目；独立运行，仅依赖环境已装的 `kubectl`。
- 本 ADR 先行、独立 commit，实现紧随其后；均走 `feat/npu-top` → PR。
