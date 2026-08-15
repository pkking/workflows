---
name: npu-top
description: top-style live TUI showing NPU (Ascend) count, model, occupancy, queued pods, and abnormal pods across all clusters reachable from a directory of kubeconfigs. Use when the user wants to monitor real-time NPU resource utilization across multiple k8s clusters, check occupancy rate (occupied by k8s / total), see how many pods are queued (Pending) or abnormal (Pending>20min or Running>60min), all refreshed like the top command.
---

# NPU-Top — 跨集群 NPU 资源 TUI 监控

扫描一个目录下所有 kubeconfig，对每个可达集群拉取 NPU 资源（Ascend 扩展资源）与 Pod 状态，渲染 `top` 风格的实时界面：顶部汇总（总 NPU、占用 NPU、占用率、排队 Pod、异常 Pod），下方节点/Pod 表格，定时刷新。

## Run

纯 stdlib（curses + subprocess 调 kubectl），无需 `uv sync`，仅需环境已装的 `kubectl`。

```bash
# 实时 TUI（默认 30s 刷新）
python3 .agents/skills/npu-top/scripts/npu_top.py /root/kubeconfig

# 调刷新间隔
python3 .agents/skills/npu-top/scripts/npu_top.py /root/kubeconfig --interval 10

# 一次性快照（纯文本，适合脚本/agent/无 TTY）
python3 .agents/skills/npu-top/scripts/npu_top.py /root/kubeconfig --once

# 自检（合成数据，验证分类与渲染逻辑）
python3 .agents/skills/npu-top/scripts/npu_top.py --mock --once
```

## TUI 键位

`q` 退出 ｜ `r` 立即刷新 ｜ `+`/`-` 调间隔 ｜ `1` 节点视图 ｜ `2` Pod 视图

## 指标定义

- **NPU 发现**：从节点 `status.capacity` 识别扩展资源，匹配 `huawei.com/ascend*`（含 ModelArts/CCE 的小写 `ascend-1980` 命名）、`huawei.com/Ascend910B`（HAMi 大写命名）、`huawei.com/npu`。型号优先取 node label `node.kubernetes.io/npu.chip.name`（如 `Ascend910`），回退 `accelerator/huawei-npu`，再回退资源名。`-memory` 后缀为 vNPU 切片，单独计入 SLICE 列、不重复算物理卡。
- **占用率**：`occupied = 该节点 pod 的 NPU request 之和`，`occupancy = occupied / capacity`。用 pod-request 口径而非 `capacity−allocatable`——因为 ModelArts/CCE 设备插件不扣减 allocatable（`capacity==allocatable` 即使有 pod 占用），pod-request 是调度可见真实占用。可能 >100%（超卖/切片）属正常信号。
- **排队 Pod**：`phase == Pending`（全部 pod，不限于 NPU）。
- **异常 Pod**：只统计**请求了 NPU 资源的 pod**，Pending 且创建至今 > `--pending-warn`（默认 20min）；或 Running 且 `startTime` 至今 > `--running-warn`（默认 60min）。排除常驻系统服务（arc-systems runner/controller 等运行数天的非 NPU pod），只抓 NPU 工作负载的卡死。阈值面向 CI 场景，训练集群请调大 `--running-warn`。

## 不可达集群

目录里的 kubeconfig 指向固定集群，本机未必都能连通。不可达集群不阻断其它集群，在结果里标 `UNREACHABLE` 一行带过（`--request-timeout=8s`，子进程上限 12s）。非 kubeconfig 文件本地 `kubectl config` 校验后直接标 `not a kubeconfig`，不占网络超时。

## 依赖与边界

- 仅依赖 `kubectl`（环境已装）。零 Python 依赖，无 `uv sync`。
- `--once` 供 agent/CI 消费；交互式 TUI 需 TTY。
- **取消代理直连**：若环境设了 `http_proxy`，`kubectl` 连集群会走代理导致 TLS 握手失败，需 `env -u http_proxy -u https_proxy ... python3 npu_top.py ...` 取消代理再跑。
- 已知上限（见 ADR-010）：纯切片（vNPU）集群物理占用率会低估（切片只扣 `-memory`）；异常阈值面向 CI 场景；网络瞬时抖动会让某集群某轮 `UNREACHABLE`，下轮刷新恢复。
