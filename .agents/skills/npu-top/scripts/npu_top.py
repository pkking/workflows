#!/usr/bin/env python3
"""npu_top — top-style TUI for NPU utilization across clusters from a kubeconfig directory.

Scans a directory of kubeconfigs, queries each reachable cluster for NPU resources
(Ascend extended resources) and pod status, and renders a live `top`-like view:
summary stats on top (occupancy, queued pods, abnormal pods), per-node / per-pod tables below.

Pure stdlib (curses, subprocess, json, argparse, datetime, collections). Needs `kubectl` on PATH.

Usage:
    python3 npu_top.py /root/kubeconfig                 # live TUI, 30s refresh
    python3 npu_top.py /root/kubeconfig --interval 10   # 10s refresh
    python3 npu_top.py /root/kubeconfig --once          # one snapshot, plain text
    python3 npu_top.py --mock --once                    # self-check, synthetic data
"""
from __future__ import annotations

import argparse
import curses
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone

# --- NPU resource conventions (HAMi / ascend-device-plugin / ModelArts CCE) ----------
# Physical cards (HAMi device-plugin): huawei.com/Ascend910A, huawei.com/Ascend910B,
# huawei.com/Ascend910B2/B3, huawei.com/Ascend310P, huawei.com/Ascend310, huawei.com/npu.
# ModelArts/CCE ascend-device-plugin: huawei.com/ascend-1980 (lowercase + chip-spec id).
# Sliced vNPU: same names with a -memory suffix (e.g. huawei.com/Ascend910B-memory).
# Model/type is NOT reliably in the resource name; prefer node labels:
#   node.kubernetes.io/npu.chip.name = Ascend910
#   accelerator/huawei-npu = ascend-snt9c
#   node-role.kubernetes.io/ascend-910c | node-role.kubernetes.io/npu-a3-560t
_NPU_RES_RE = re.compile(
    r"^(huawei\.com/(?:npu|ascend(?:-\d+|\d+[A-Z0-9]*)?))(-memory)?$", re.I)
# Also catch bare ascend/npu keys some plugins use.
_NPU_RES_RE2 = re.compile(r"(?:^|/)(ascend(?:-\d+|\d+[a-z0-9]*)?|npu)(-memory)?$", re.I)

# Thresholds (minutes) — CI context defaults; override via CLI.
DEFAULT_PENDING_WARN = 20
DEFAULT_RUNNING_WARN = 60
DEFAULT_INTERVAL = 30


def is_npu_resource(name: str) -> bool:
    return bool(_NPU_RES_RE.match(name) or _NPU_RES_RE2.search(name))


def is_memory_slice(name: str) -> bool:
    return name.lower().endswith("-memory") or name.lower().endswith("/memory")


def extract_model(name: str) -> str:
    """huawei.com/Ascend910B -> 910B; huawei.com/npu -> NPU; fallback to last segment."""
    m = _NPU_RES_RE.match(name)
    if m:
        core = m.group(1).split("/")[-1]
        return "NPU" if core.lower() == "npu" else core.replace("Ascend", "")
    m = _NPU_RES_RE2.search(name)
    if m:
        core = m.group(1)
        return "NPU" if core.lower() == "npu" else core
    return name.rsplit("/", 1)[-1]


# --- Data model -------------------------------------------------------------

@dataclass
class NodeInfo:
    name: str
    cluster: str
    capacity: dict[str, int] = field(default_factory=dict)
    allocatable: dict[str, int] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    # physical NPU models -> total/occupied/occupancy
    npu: dict[str, dict] = field(default_factory=dict)  # model -> {total, occupied, occ%}
    slice_used: dict[str, int] = field(default_factory=dict)  # model -> slice pod count

    def model_from_labels(self) -> str:
        """Resolve NPU chip model from node labels (preferred over resource name)."""
        chip = self.labels.get("node.kubernetes.io/npu.chip.name")
        if chip:
            return chip  # e.g. Ascend910
        acc = self.labels.get("accelerator/huawei-npu")
        if acc:
            return acc  # e.g. ascend-snt9c
        # node-role.kubernetes.io/ascend-910c | npu-a3-560t keys
        for k in self.labels:
            kl = k.lower()
            if "ascend-" in kl or kl.startswith("node-role.kubernetes.io/npu"):
                seg = k.rsplit("/", 1)[-1]
                return seg
        return ""

    def compute_npu(self, requests_by_res: dict[str, float] | None = None) -> None:
        """Occupancy by pod-request: occupied = sum of pod NPU requests on this node.

        Device plugins (esp. ModelArts/CCE) often don't decrement allocatable, so
        capacity-allocatable reads 0% even when pods hold NPUs. Pod-request is the
        scheduler-visible truth: sum of requested units / capacity. May exceed 100%
        when oversubscribed/sliced — that's informative, not a bug.
        """
        label_model = self.model_from_labels()
        requests_by_res = requests_by_res or {}
        for res, cap in self.capacity.items():
            if not is_npu_resource(res):
                continue
            if is_memory_slice(res):
                continue  # memory slices counted separately, not as physical cards
            model = label_model or extract_model(res)
            occupied = int(requests_by_res.get(res, 0))
            # cap=0 guard; clamp physical-card count to capacity to avoid silly >cap
            occ = (occupied / cap * 100) if cap else 0.0
            self.npu[model] = {"total": cap, "occupied": occupied, "occ": occ}


@dataclass
class PodInfo:
    name: str
    namespace: str
    cluster: str
    node: str
    phase: str
    created_ts: str | None
    start_ts: str | None
    npu_requests: dict[str, float] = field(default_factory=dict)
    # derived
    age_min: float = 0.0
    run_min: float = 0.0
    queued: bool = False
    abnormal: bool = False
    model: str = ""

    def classify(self, now: datetime, pending_warn: float, running_warn: float) -> None:
        self.queued = self.phase == "Pending"
        self.run_min = _age_min(self.start_ts, now) if self.start_ts else 0.0
        age_min = _age_min(self.created_ts, now) if self.created_ts else 0.0
        self.age_min = age_min
        # abnormal targets NPU workloads only: long-lived system services (arc-systems
        # runners, controllers) running for days are normal, not stuck CI. A pod is
        # abnormal only if it holds NPU resources and exceeds the thresholds.
        has_npu = any(is_npu_resource(r) for r in self.npu_requests)
        self.abnormal = has_npu and (
            (self.phase == "Pending" and age_min > pending_warn)
            or (self.phase == "Running" and self.run_min > running_warn)
        )
        # model from NPU requests (first physical)
        for res in self.npu_requests:
            if is_npu_resource(res) and not is_memory_slice(res):
                self.model = extract_model(res)
                break


@dataclass
class ClusterSnapshot:
    cluster: str
    source: str
    reachable: bool = True
    error: str = ""
    nodes: list[NodeInfo] = field(default_factory=list)
    pods: list[PodInfo] = field(default_factory=list)
    # aggregates
    total_by_model: dict[str, int] = field(default_factory=dict)
    occupied_by_model: dict[str, int] = field(default_factory=dict)
    slice_pods_by_model: dict[str, int] = field(default_factory=dict)
    queued_pods: int = 0
    abnormal_pods: int = 0

    def aggregate(self) -> None:
        for n in self.nodes:
            for model, d in n.npu.items():
                self.total_by_model[model] = self.total_by_model.get(model, 0) + d["total"]
                self.occupied_by_model[model] = self.occupied_by_model.get(model, 0) + d["occupied"]
            for model, c in n.slice_used.items():
                self.slice_pods_by_model[model] = self.slice_pods_by_model.get(model, 0) + c
        for p in self.pods:
            if p.queued:
                self.queued_pods += 1
            if p.abnormal:
                self.abnormal_pods += 1

    @property
    def total_npu(self) -> int:
        return sum(self.total_by_model.values())

    @property
    def occupied_npu(self) -> int:
        return sum(self.occupied_by_model.values())

    @property
    def occupancy(self) -> float:
        return (self.occupied_npu / self.total_npu * 100) if self.total_npu else 0.0


# --- k8s helpers ------------------------------------------------------------

def _age_min(ts: str | None, now: datetime) -> float:
    """RFC3339 timestamp -> minutes elapsed until `now`."""
    if not ts:
        return 0.0
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return max((now - t).total_seconds() / 60.0, 0.0)
    except Exception:
        return 0.0


def _run_kubectl(kubeconfig: str, args: list[str], timeout: float = 10.0) -> dict:
    """Run kubectl --kubeconfig=... with json output. Returns parsed dict or raises."""
    cmd = ["kubectl", f"--kubeconfig={kubeconfig}", "--request-timeout=8s"] + args
    r = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "KUBECONFIG": kubeconfig},
    )
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip().splitlines()
        raise RuntimeError(err[-1] if err else "kubectl failed")
    return json.loads(r.stdout)


def _cluster_name(path: str) -> str:
    base = os.path.basename(path)
    for ext in (".yaml", ".yml", ".json", ".kubeconfig", ".ymlx"):
        if base.lower().endswith(ext):
            base = base[: -len(ext)]
    return base or path


def _is_kubeconfig(kubeconfig: str) -> bool:
    """Quick local-only check: does kubectl recognize this file as a kubeconfig?"""
    try:
        r = subprocess.run(
            ["kubectl", f"--kubeconfig={kubeconfig}", "config", "current-context"],
            capture_output=True, text=True, timeout=5,
            env={**os.environ, "KUBECONFIG": kubeconfig},
        )
        return r.returncode == 0
    except Exception:
        return False


def probe_cluster(kubeconfig: str) -> ClusterSnapshot:
    """Probe one kubeconfig: nodes + pods. Unreachable -> reachable=False snapshot."""
    cname = _cluster_name(kubeconfig)
    snap = ClusterSnapshot(cluster=cname, source=kubeconfig)
    if not _is_kubeconfig(kubeconfig):
        snap.reachable = False
        snap.error = "not a kubeconfig"
        return snap
    try:
        now = datetime.now(timezone.utc)
        # pods first: aggregate NPU requests per node for occupancy calc
        pods_data = _run_kubectl(kubeconfig, ["get", "pods", "-A", "-o", "json"], timeout=12)
        node_requests: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for item in pods_data.get("items", []):
            md = item.get("metadata", {})
            spec = item.get("spec", {})
            status = item.get("status", {})
            req: dict[str, float] = {}
            for c in spec.get("containers", []):
                for rkey, rval in (c.get("resources", {}).get("limits") or {}).items():
                    try:
                        req[rkey] = req.get(rkey, 0) + float(rval)
                    except (ValueError, TypeError):
                        pass
            p = PodInfo(
                name=md.get("name", "?"),
                namespace=md.get("namespace", "?"),
                cluster=cname,
                node=spec.get("nodeName", "") or "",
                phase=status.get("phase", "Unknown"),
                created_ts=md.get("creationTimestamp"),
                start_ts=status.get("startTime"),
                npu_requests=req,
            )
            p.classify(now, DEFAULT_PENDING_WARN, DEFAULT_RUNNING_WARN)
            # physical NPU requests accrue to this node's occupancy
            for res, qty in req.items():
                if is_npu_resource(res) and not is_memory_slice(res):
                    if p.node:
                        node_requests[p.node][res] += qty
            slice_models = [
                extract_model(res) for res in req
                if is_npu_resource(res) and is_memory_slice(res)
            ]
            for model in slice_models:
                p.model = p.model or model
            snap.pods.append(p)

        # nodes: compute NPU with per-node pod-request occupancy
        nodes_data = _run_kubectl(kubeconfig, ["get", "nodes", "-o", "json"], timeout=12)
        for item in nodes_data.get("items", []):
            name = item.get("metadata", {}).get("name", "?")
            cap = item.get("status", {}).get("capacity", {})
            alloc = item.get("status", {}).get("allocatable", {})
            labels = item.get("metadata", {}).get("labels", {})
            # coerce "1"/"8" strings -> int; skip non-numeric
            cap = {k: int(v) for k, v in cap.items() if str(v).isdigit()}
            alloc = {k: int(v) for k, v in alloc.items() if str(v).isdigit()}
            n = NodeInfo(name=name, cluster=cname, capacity=cap, allocatable=alloc,
                         labels=labels)
            n.compute_npu(dict(node_requests.get(name, {})))
            # slice pod counts by model (for SLICE column)
            for p in snap.pods:
                if p.node == name:
                    for res in p.npu_requests:
                        if is_npu_resource(res) and is_memory_slice(res):
                            m = n.model_from_labels() or extract_model(res)
                            n.slice_used[m] = n.slice_used.get(m, 0) + 1
            snap.nodes.append(n)
        snap.aggregate()
    except (subprocess.TimeoutExpired, RuntimeError, json.JSONDecodeError) as e:
        snap.reachable = False
        if isinstance(e, subprocess.TimeoutExpired):
            snap.error = "kubectl timeout (cluster unreachable)"
        else:
            snap.error = str(e)[:120]
    return snap


def collect_all(kubeconfig_dir: str, concurrency: int = 8) -> list[ClusterSnapshot]:
    """Scan dir for candidate kubeconfigs and probe each in parallel."""
    files = []
    for entry in sorted(os.listdir(kubeconfig_dir)):
        p = os.path.join(kubeconfig_dir, entry)
        if not os.path.isfile(p):
            continue
        # skip obvious non-config files
        if entry.startswith(".") or entry.lower() in {"readme", "readme.md", "license"}:
            continue
        files.append(p)
    snaps: list[ClusterSnapshot] = []
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = {ex.submit(probe_cluster, f): f for f in files}
        for fut in as_completed(futs):
            snaps.append(fut.result())
    snaps.sort(key=lambda s: s.cluster)
    return snaps


# --- synthetic mock (self-check / --mock) -----------------------------------

def mock_snapshots() -> list[ClusterSnapshot]:
    def mknode(cname, name, chip, total, occ):
        occupied = round(total * occ / 100)
        # use real ModelArts naming: resource ascend-1980 + chip.name label
        return NodeInfo(
            name=name, cluster=cname,
            capacity={"huawei.com/ascend-1980": total},
            allocatable={"huawei.com/ascend-1980": total - occupied},
            labels={"node.kubernetes.io/npu.chip.name": chip},
        )

    s1 = ClusterSnapshot(cluster="ascend-ci-prod", source="<mock>")
    s1.nodes = [
        mknode(s1.cluster, "node-a1", "Ascend910", 8, 0),
        mknode(s1.cluster, "node-a2", "Ascend910", 8, 0),
        mknode(s1.cluster, "node-a3", "Ascend310", 4, 0),
    ]
    now = datetime.now(timezone.utc)
    # a queued pod (>20min), an abnormal running pod (>60min), a normal running pod
    from datetime import timedelta
    RES = "huawei.com/ascend-1980"
    p_queued = PodInfo("job-x", "ci", s1.cluster, "", "Pending",
                        created_ts=(now - timedelta(minutes=25)).isoformat(),
                        start_ts=None)
    p_queued.classify(now, DEFAULT_PENDING_WARN, DEFAULT_RUNNING_WARN)
    p_abn = PodInfo("job-y", "ci", s1.cluster, "node-a1", "Running",
                    created_ts=(now - timedelta(minutes=70)).isoformat(),
                    start_ts=(now - timedelta(minutes=70)).isoformat())
    p_abn.npu_requests = {RES: 6}  # occupies 6/8 on node-a1; set before classify
    p_abn.classify(now, DEFAULT_PENDING_WARN, DEFAULT_RUNNING_WARN)
    p_ok = PodInfo("job-z", "ci", s1.cluster, "node-a2", "Running",
                   created_ts=(now - timedelta(minutes=5)).isoformat(),
                   start_ts=(now - timedelta(minutes=5)).isoformat())
    p_ok.npu_requests = {RES: 8}  # fills node-a2 (8/8)
    p_ok.classify(now, DEFAULT_PENDING_WARN, DEFAULT_RUNNING_WARN)
    p_ok.model = "Ascend910"
    p_slice = PodInfo("job-w", "ci", s1.cluster, "node-a3", "Running",
                      created_ts=(now - timedelta(minutes=3)).isoformat(),
                      start_ts=(now - timedelta(minutes=3)).isoformat())
    p_slice.npu_requests = {"huawei.com/Ascend310-memory": 2000}
    p_slice.classify(now, DEFAULT_PENDING_WARN, DEFAULT_RUNNING_WARN)
    # compute per-node NPU occupancy from pod requests (node-a1: 6/8, node-a2: 8/8)
    node_req = defaultdict(lambda: defaultdict(float))
    for p in (p_abn, p_ok):
        for res, qty in p.npu_requests.items():
            node_req[p.node][res] += qty
    s1.nodes[0].compute_npu(dict(node_req["node-a1"]))
    s1.nodes[1].compute_npu(dict(node_req["node-a2"]))
    s1.nodes[2].compute_npu({})
    s1.nodes[2].slice_used["Ascend310"] = 1
    s1.pods = [p_queued, p_abn, p_ok, p_slice]
    s1.aggregate()

    s2 = ClusterSnapshot(cluster="ascend-hk-001", source="<mock>", reachable=False,
                         error="TLS handshake timeout")
    return [s1, s2]


# --- plain-text renderer (--once / non-tty) --------------------------------

def render_text(snaps: list[ClusterSnapshot]) -> str:
    out: list[str] = []
    ttotal = sum(s.total_npu for s in snaps)
    tocc = sum(s.occupied_npu for s in snaps)
    tqueued = sum(s.queued_pods for s in snaps)
    tabn = sum(s.abnormal_pods for s in snaps)
    occ = (tocc / ttotal * 100) if ttotal else 0.0
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    out.append(f"NPU-Top  snapshot @ {now}")
    out.append(f"clusters: {len(snaps)}  |  NPU total: {ttotal}  occupied: {tocc}  "
               f"occupancy: {occ:.1f}%  |  queued pods: {tqueued}  abnormal: {tabn}")
    out.append("=" * 92)

    for s in snaps:
        if not s.reachable:
            out.append(f"[{s.cluster}] UNREACHABLE: {s.error}")
            out.append("")
            continue
        out.append(f"[{s.cluster}]  NPU {s.occupied_npu}/{s.total_npu} "
                   f"({s.occupancy:.1f}%)  queued: {s.queued_pods}  abnormal: {s.abnormal_pods}")
        out.append(f"  {'NODE':<28}{'MODEL':<8}{'TOTAL':>6}{'USED':>6}{'OCC%':>7}{'SLICE':>7}")
        for n in s.nodes:
            if not n.npu:
                continue
            for model, d in n.npu.items():
                sl = n.slice_used.get(model, 0)
                out.append(f"  {n.name[:28]:<28}{model:<8}{d['total']:>6}{d['occupied']:>6}"
                           f"{d['occ']:>6.1f}%{sl:>7}")
        # abnormal pod detail
        abn = [p for p in s.pods if p.abnormal]
        if abn:
            out.append(f"  -- abnormal pods ({len(abn)}) --")
            for p in abn:
                tag = f"PENDING {p.age_min:.0f}min" if p.queued else f"RUNNING {p.run_min:.0f}min"
                out.append(f"  {p.namespace}/{p.name[:30]:<30} {p.phase:<10} {tag}")
        out.append("")
    return "\n".join(out)


# --- curses TUI -------------------------------------------------------------

def _color_pairs() -> None:
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_RED, -1)      # abnormal / high occ
    curses.init_pair(2, curses.COLOR_YELLOW, -1)    # warn
    curses.init_pair(3, curses.COLOR_GREEN, -1)     # healthy / low occ
    curses.init_pair(4, curses.COLOR_CYAN, -1)      # headers
    curses.init_pair(5, curses.COLOR_WHITE, curses.COLOR_RED)  # unreachable bg


def _occ_color(occ: float) -> int:
    if occ >= 85:
        return curses.color_pair(1)
    if occ >= 60:
        return curses.color_pair(2)
    return curses.color_pair(3)


def _draw(stdscr: curses.wrapper, snaps: list[ClusterSnapshot], interval: int,
          view: int, collecting: bool) -> tuple[int, int]:
    """Draw one frame. Returns (new_interval, new_view)."""
    stdscr.erase()
    H, W = stdscr.getmaxyx()
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    row = 0

    # title
    stdscr.addstr(row, 0, f"NPU-Top  {now}  refresh {interval}s  view: "
                  f"{'nodes' if view == 1 else 'pods'}"
                  f"{'  [refreshing...]' if collecting else ''}",
                  curses.color_pair(4) | curses.A_BOLD)
    row += 1

    # global summary
    ttotal = sum(s.total_npu for s in snaps)
    tocc = sum(s.occupied_npu for s in snaps)
    tqueued = sum(s.queued_pods for s in snaps)
    tabn = sum(s.abnormal_pods for s in snaps)
    occ = (tocc / ttotal * 100) if ttotal else 0.0
    nclu = sum(1 for s in snaps if s.reachable)
    stdscr.addstr(row, 0, f"clusters {nclu}/{len(snaps)}  NPU {tocc}/{ttotal}  "
                  f"occupancy ", curses.A_BOLD)
    stdscr.addstr(f"{occ:.1f}%", _occ_color(occ) | curses.A_BOLD)
    stdscr.addstr(f"  queued {tqueued}", curses.color_pair(3 if tqueued == 0 else 2))
    stdscr.addstr(f"  abnormal {tabn}", curses.color_pair(3 if tabn == 0 else 1))
    row += 2

    if view == 1:
        # per-cluster node table
        stdscr.addstr(row, 0, f"{'CLUSTER':<22}{'NODE':<26}{'MODEL':<7}"
                      f"{'TOTAL':>6}{'USED':>6}{'OCC%':>7}{'SLICE':>7}", curses.color_pair(4))
        row += 1
        for s in snaps:
            if not s.reachable:
                stdscr.addstr(row, 0, f"{s.cluster[:22]:<22}UNREACHABLE: {s.error[:W-30]}",
                              curses.color_pair(5))
                row += 1
                if row >= H - 1:
                    break
                continue
            for n in s.nodes:
                if not n.npu:
                    continue
                for model, d in n.npu.items():
                    if row >= H - 1:
                        break
                    sl = n.slice_used.get(model, 0)
                    left = (f"{s.cluster[:22]:<22}{n.name[:26]:<26}{model:<7}"
                            f"{d['total']:>6}{d['occupied']:>6}")
                    occ_s = f"{d['occ']:5.1f}%"
                    right = f"{sl:>7}"
                    col = len(left)
                    stdscr.addstr(row, 0, (left + right)[:W])
                    if col + len(occ_s) <= W:
                        stdscr.addstr(row, col, occ_s, _occ_color(d["occ"]))
                    row += 1
                if row >= H - 1:
                    break
        # abnormal pod summary tail
        abn_all = [p for s in snaps if s.reachable for p in s.pods if p.abnormal]
        if row < H - 1 and abn_all:
            stdscr.addstr(row, 0, f"-- abnormal pods ({len(abn_all)}) --", curses.color_pair(1))
            row += 1
            for p in abn_all[: H - row - 2]:
                tag = f"PENDING {p.age_min:.0f}m" if p.queued else f"RUNNING {p.run_min:.0f}m"
                stdscr.addstr(row, 0, f"  {p.cluster[:14]:<14}{p.namespace[:12]:<12}"
                              f"{p.name[:24]:<24}{tag}", curses.color_pair(2))
                row += 1
    else:
        # pod view: abnormal + running NPU pods
        pods = [p for s in snaps if s.reachable for p in s.pods
                if p.abnormal or p.npu_requests]
        stdscr.addstr(row, 0, f"{'CLUSTER':<16}{'NS':<12}{'POD':<26}{'PHASE':<10}"
                      f"{'MODEL':<7}{'AGE':>7}{'RUN':>7}", curses.color_pair(4))
        row += 1
        for p in pods[: H - row - 2]:
            cp = curses.color_pair(1) if p.abnormal else curses.color_pair(2) if p.queued else 0
            stdscr.addstr(row, 0, f"{p.cluster[:16]:<16}{p.namespace[:12]:<12}"
                          f"{p.name[:26]:<26}{p.phase[:10]:<10}{p.model:<7}"
                          f"{p.age_min:>6.0f}m{p.run_min:>6.0f}m", cp)
            row += 1

    stdscr.addstr(H - 1, 0, "q quit | r refresh | +/- interval | 1 nodes | 2 pods",
                  curses.color_pair(4))
    stdscr.refresh()
    return interval, view


def tui_main(kubeconfig_dir: str, interval: int, concurrency: int) -> int:
    def _loop(stdscr):
        curses.curs_set(0)
        stdscr.timeout(int(interval * 1000))
        _color_pairs()
        view = 1
        snaps: list[ClusterSnapshot] = []
        collecting = False
        while True:
            if not snaps or not collecting:
                collecting = True
                try:
                    snaps = collect_all(kubeconfig_dir, concurrency)
                except Exception as e:  # pragma: no cover
                    snaps = [ClusterSnapshot(cluster="error", source="", reachable=False,
                                             error=str(e)[:120])]
                collecting = False
            _draw(stdscr, snaps, interval, view, collecting)
            ch = stdscr.getch()
            if ch in (ord("q"), ord("Q")):
                break
            elif ch in (ord("r"), ord("R")):
                continue
            elif ch == ord("+") or ch == ord("="):
                interval = min(interval + 10, 600)
                stdscr.timeout(int(interval * 1000))
            elif ch == ord("-"):
                interval = max(interval - 10, 5)
                stdscr.timeout(int(interval * 1000))
            elif ch == ord("1"):
                view = 1
            elif ch == ord("2"):
                view = 2
    curses.wrapper(_loop)
    return 0


# --- CLI / self-check -------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    global DEFAULT_PENDING_WARN, DEFAULT_RUNNING_WARN
    ap = argparse.ArgumentParser(description="top-style TUI for NPU utilization across clusters")
    ap.add_argument("dir", nargs="?", help="directory of kubeconfigs")
    ap.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                    help="refresh interval seconds (default 30)")
    ap.add_argument("--concurrency", type=int, default=8, help="parallel cluster probes")
    ap.add_argument("--once", action="store_true", help="print one snapshot as text, no TUI")
    ap.add_argument("--mock", action="store_true", help="use synthetic data (self-check)")
    ap.add_argument("--pending-warn", type=float, default=DEFAULT_PENDING_WARN,
                    help="Pending>min -> abnormal (default 20)")
    ap.add_argument("--running-warn", type=float, default=DEFAULT_RUNNING_WARN,
                    help="Running>min -> abnormal (default 60)")
    args = ap.parse_args(argv)

    # ponytail: thresholds wired to module globals so probe/mock use CLI overrides.
    DEFAULT_PENDING_WARN = args.pending_warn
    DEFAULT_RUNNING_WARN = args.running_warn

    if args.mock:
        snaps = mock_snapshots()
        print(render_text(snaps))
        # self-check assertions
        s1 = snaps[0]
        assert s1.queued_pods == 1, f"queued: {s1.queued_pods}"
        assert s1.abnormal_pods == 1, f"abnormal: {s1.abnormal_pods}"  # NPU pod Running>60min
        assert s1.total_npu == 20, f"total: {s1.total_npu}"
        assert abs(s1.occupancy - 70.0) < 0.1, f"occ: {s1.occupancy}"  # 14/20 pod-request
        assert not snaps[1].reachable
        print("\n[self-check OK] queued=1 abnormal=1 total=20 occ=70.0%")
        return 0

    if not args.dir:
        ap.error("directory required (or use --mock)")

    if not os.path.isdir(args.dir):
        ap.error(f"not a directory: {args.dir}")

    if args.once:
        snaps = collect_all(args.dir, args.concurrency)
        print(render_text(snaps))
        return 0

    return tui_main(args.dir, args.interval, args.concurrency)


if __name__ == "__main__":
    sys.exit(main())
