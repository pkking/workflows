#!/usr/bin/env python3
"""PM 需求进展分析工具

分析 GitHub Issue，输出需求进展看板：
  - 未接受需求（有 enhancement 但无 accepted）
  - 异常需求分类（无交付时间 / 无责任人）

用法:
  python3 pm_progress.py [--repo owner/name] [--state open|closed|all] [--json] [--html FILE] [--action]
"""

import argparse
import json
import os
import re
import sys
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------
@dataclass
class Issue:
    number: int
    title: str
    state: str
    labels: list[str] = field(default_factory=list)
    milestone_title: Optional[str] = None
    assignee: Optional[str] = None


# ---------------------------------------------------------------------------
# 数据获取层 — GitHub REST API
# ---------------------------------------------------------------------------
def _api_get(url: str, token: str) -> dict:
    """调用 GitHub REST API，返回 JSON。"""
    import urllib.request
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def fetch_issues(repo: str, state: str = "open", limit: int = 200) -> list[Issue]:
    """通过 GitHub REST API 拉取 issue 列表。"""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("环境变量 GITHUB_TOKEN 未设置")

    # GitHub API 每次最多返回 100 条，需要分页
    issues: list[Issue] = []
    page = 1
    per_page = 100
    while len(issues) < limit:
        url = (
            f"https://api.github.com/repos/{repo}/issues"
            f"?state={state}&per_page={per_page}&page={page}"
        )
        items = _api_get(url, token)
        if not items:
            break
        for item in items:
            # 过滤掉 PR（issues API 会同时返回 PR）
            if "pull_request" in item:
                continue
            labels = [lbl["name"] for lbl in item.get("labels", [])]
            milestone = item.get("milestone")
            assignees = item.get("assignees", [])
            issues.append(Issue(
                number=item["number"],
                title=item["title"],
                state=item.get("state", "open"),
                labels=labels,
                milestone_title=milestone.get("title") if milestone else None,
                assignee=assignees[0]["login"] if assignees else None,
            ))
            if len(issues) >= limit:
                break
        page += 1
        if len(items) < per_page:
            break
    return issues


# ---------------------------------------------------------------------------
# 分析层
# ---------------------------------------------------------------------------
def analyze(issues: list[Issue]):
    """返回分析结果字典。"""
    enhancements = [i for i in issues if "enhancement" in i.labels]

    accepted = []
    unaccepted = []
    abnormal_no_milestone = []
    abnormal_no_assignee = []
    unaccepted_anomalies = []

    for iss in enhancements:
        is_accepted = "accepted" in iss.labels
        anomaly_reasons: list[str] = []

        if not iss.milestone_title:
            anomaly_reasons.append("无交付时间")
        if not iss.assignee:
            anomaly_reasons.append("无责任人")

        if is_accepted:
            accepted.append((iss, anomaly_reasons))
            if "无交付时间" in anomaly_reasons:
                abnormal_no_milestone.append(iss)
            if "无责任人" in anomaly_reasons:
                abnormal_no_assignee.append(iss)
        else:
            unaccepted.append((iss, anomaly_reasons))
            if anomaly_reasons:
                unaccepted_anomalies.append((iss, anomaly_reasons))

    return {
        "total_enhancement": len(enhancements),
        "accepted": accepted,
        "unaccepted": unaccepted,
        "abnormal_no_milestone": abnormal_no_milestone,
        "abnormal_no_assignee": abnormal_no_assignee,
        "unaccepted_anomalies": unaccepted_anomalies,
    }


# ---------------------------------------------------------------------------
# 展示层 — 终端表格
# ---------------------------------------------------------------------------
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _col(text: str, color: str) -> str:
    return f"{color}{text}{RESET}"


def _pad(text: str, width: int) -> str:
    plain = re.sub(r"\033\[[0-9;]*m", "", text)
    return text + " " * (width - len(plain))


def _table(headers: list[str], rows: list[list[str]], color_fn=None) -> str:
    col_widths = [len(h) for h in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            col_widths[idx] = max(col_widths[idx], len(cell))

    sep = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"
    header_line = "|" + "|".join(
        f" {_pad(h, w)} " for h, w in zip(headers, col_widths)
    ) + "|"

    lines = [BOLD + sep + RESET, BOLD + header_line + RESET, BOLD + sep + RESET]
    for row in rows:
        cells = []
        for idx, cell in enumerate(row):
            display = _pad(cell, col_widths[idx])
            if color_fn:
                display = color_fn(idx, display, cell)
            cells.append(f" {display} ")
        lines.append("|" + "|".join(cells) + "|")
    lines.append(BOLD + sep + RESET)
    return "\n".join(lines)


def print_dashboard(result: dict, as_json: bool = False):
    if as_json:
        output = {
            "summary": {
                "total_enhancement": result["total_enhancement"],
                "accepted_count": len(result["accepted"]),
                "unaccepted_count": len(result["unaccepted"]),
                "abnormal_no_milestone": len(result["abnormal_no_milestone"]),
                "abnormal_no_assignee": len(result["abnormal_no_assignee"]),
            },
            "accepted": [
                {"number": i.number, "title": i.title, "milestone": i.milestone_title,
                 "assignee": i.assignee, "anomalies": a}
                for i, a in result["accepted"]
            ],
            "unaccepted": [
                {"number": i.number, "title": i.title, "milestone": i.milestone_title,
                 "assignee": i.assignee, "anomalies": a}
                for i, a in result["unaccepted"]
            ],
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return

    total = result["total_enhancement"]
    accepted_count = len(result["accepted"])
    unaccepted_count = len(result["unaccepted"])

    print()
    print(f"  {_col('📋 PM 需求进展看板', BOLD + CYAN)}")
    print(f"  {_col('━' * 50, CYAN)}")
    print(f"  需求总数: {_col(str(total), BOLD)}")
    print(f"  已接受:   {_col(str(accepted_count), GREEN)}")
    print(f"  未接受:   {_col(str(unaccepted_count), YELLOW)}")
    print()

    print(f"  {_col('✅ 已接受需求', GREEN + BOLD)}")
    if result["accepted"]:
        headers = ["#", "标题", "里程碑", "责任人", "异常"]
        rows = []
        for iss, anomalies in result["accepted"]:
            flag = _col("⚠ " + ",".join(anomalies), YELLOW) if anomalies else _col("✓", GREEN)
            rows.append([str(iss.number), iss.title,
                         iss.milestone_title or _col("—", RED),
                         iss.assignee or _col("—", RED), flag])

        def _color(idx, display, cell):
            return _col(display, CYAN) if idx == 0 else display

        print(_table(headers, rows, _color))
    else:
        print(f"  {_col('  （无）', GREEN)}")
    print()

    print(f"  {_col('📌 未接受需求', YELLOW + BOLD)}")
    if result["unaccepted"]:
        headers = ["#", "标题", "里程碑", "责任人", "异常"]
        rows = []
        for iss, anomalies in result["unaccepted"]:
            flag = _col("⚠ " + ",".join(anomalies), YELLOW) if anomalies else ""
            rows.append([str(iss.number), iss.title,
                         iss.milestone_title or "—", iss.assignee or "—", flag])
        print(_table(headers, rows))
    else:
        print(f"  {_col('  （无）', GREEN)}")
    print()

    print(f"  {_col('🚨 异常需求汇总', RED + BOLD)}")
    print(f"    无交付时间: {_col(str(len(result['abnormal_no_milestone'])), BOLD)} 条")
    print(f"    无责任人:   {_col(str(len(result['abnormal_no_assignee'])), BOLD)} 条")

    all_abnormal = []
    seen = set()
    for iss, anomalies in result["accepted"]:
        if anomalies:
            all_abnormal.append((iss, anomalies))
            seen.add(iss.number)
    for iss, anomalies in result["unaccepted"]:
        if anomalies and iss.number not in seen:
            all_abnormal.append((iss, anomalies))
            seen.add(iss.number)

    if all_abnormal:
        print()
        headers = ["#", "标题", "里程碑", "责任人", "异常分类"]
        rows = []
        for iss, anomalies in all_abnormal:
            rows.append([str(iss.number), iss.title,
                         iss.milestone_title or _col("无", RED),
                         iss.assignee or _col("无", RED),
                         _col(", ".join(anomalies), RED)])
        print(_table(headers, rows))
    else:
        print(f"  {_col('  （无异常）', GREEN)}")
    print()


# ---------------------------------------------------------------------------
# 行动清单
# ---------------------------------------------------------------------------
def print_action_items(result: dict):
    repo = "opensourceways/backlog"
    url_prefix = f"https://github.com/{repo}/issues/"

    needs_accept = []
    both_missing = []
    missing_milestone = []
    missing_assignee = []

    for iss, anomalies in result["unaccepted"]:
        needs_accept.append(iss)

    for iss, anomalies in result["accepted"]:
        has_milestone = bool(iss.milestone_title)
        has_assignee = bool(iss.assignee)
        if not has_milestone and not has_assignee:
            both_missing.append(iss)
        elif not has_milestone:
            missing_milestone.append(iss)
        elif not has_assignee:
            missing_assignee.append(iss)

    total = len(needs_accept) + len(both_missing) + len(missing_milestone) + len(missing_assignee)

    print()
    print(f"  {_col(f'🎯 PM 行动清单 — 共 {total} 条待处理', BOLD + RED)}")
    print(f"  {_col('━' * 50, RED)}")
    print()

    if needs_accept:
        print(f"  {_col(f'🔴 P0 — 待评审接受（{len(needs_accept)} 条）', BOLD + RED)}")
        for iss in needs_accept:
            url = f"{url_prefix}{iss.number}"
            extra = ""
            if not iss.milestone_title:
                extra += _col("  [无交付时间]", RED)
            if not iss.assignee:
                extra += _col("  [无责任人]", RED)
            print(f"  {_col(f'#{iss.number}', CYAN)} {iss.title}{extra}")
            print(f"  {url}")
        print()

    if both_missing:
        print(f"  {_col(f'🔴 P1 — 已接受但缺交付时间和责任人（{len(both_missing)} 条）', BOLD + RED)}")
        for iss in both_missing:
            url = f"{url_prefix}{iss.number}"
            print(f"  {_col(f'#{iss.number}', CYAN)} {iss.title}")
            print(f"  {url}")
        print()

    # P2: 按责任人聚合
    if missing_milestone:
        by_assignee: dict[str, list] = defaultdict(list)
        for iss in missing_milestone:
            by_assignee[iss.assignee or "无责任人"].append(iss)
        sorted_assignees = sorted(by_assignee.items(), key=lambda x: len(x[1]), reverse=True)

        print(f"  {_col(f'🟡 P2 — 已接受但缺交付时间（{len(missing_milestone)} 条 / {len(sorted_assignees)} 人）', BOLD + YELLOW)}")
        for assignee, iss_list in sorted_assignees:
            who = _col(assignee, GREEN + BOLD) if assignee != "无责任人" else _col("无责任人", RED + BOLD)
            print(f"  {_col(f'👤 {who}（{len(iss_list)} 条）', BOLD)}")
            for iss in iss_list:
                print(f"    {_col(f'#{iss.number}', CYAN)} {iss.title}")
                print(f"    {url_prefix}{iss.number}")
        print()

    # P3: 按里程碑聚合
    if missing_assignee:
        by_milestone: dict[str, list] = defaultdict(list)
        for iss in missing_assignee:
            by_milestone[iss.milestone_title or "无交付时间"].append(iss)
        sorted_milestones = sorted(by_milestone.items(), key=lambda x: len(x[1]), reverse=True)

        print(f"  {_col(f'🟡 P3 — 已接受但缺责任人（{len(missing_assignee)} 条 / {len(sorted_milestones)} 个里程碑）', BOLD + YELLOW)}")
        for milestone, iss_list in sorted_milestones:
            when = _col(milestone, GREEN + BOLD) if milestone != "无交付时间" else _col("无交付时间", RED + BOLD)
            print(f"  {_col(f'📅 {when}（{len(iss_list)} 条）', BOLD)}")
            for iss in iss_list:
                print(f"    {_col(f'#{iss.number}', CYAN)} {iss.title}")
                print(f"    {url_prefix}{iss.number}")
        print()


# ---------------------------------------------------------------------------
# HTML 报告生成
# ---------------------------------------------------------------------------
def _html_issue_rows(issues):
    rows = ""
    none_tag = '<span class="tag red">无</span>'
    for iss in issues:
        ms = iss.milestone_title or none_tag
        asgn = iss.assignee or none_tag
        rows += (
            '<tr>'
            f'<td><a href="https://github.com/opensourceways/backlog/issues/{iss.number}" target="_blank">#{iss.number}</a></td>'
            f'<td>{iss.title}</td>'
            f'<td>{ms}</td>'
            f'<td>{asgn}</td>'
            '</tr>\n'
        )
    return rows


def generate_html(result: dict) -> str:
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    total = result["total_enhancement"]
    accepted_count = len(result["accepted"])
    unaccepted_count = len(result["unaccepted"])

    # P2 按责任人分组
    p2_by_assignee: dict[str, list] = defaultdict(list)
    for iss, _ in result["accepted"]:
        if not iss.milestone_title:
            p2_by_assignee[iss.assignee or "无责任人"].append(iss)
    p2_sorted = sorted(p2_by_assignee.items(), key=lambda x: len(x[1]), reverse=True)

    # P3 按里程碑分组
    p3_by_milestone: dict[str, list] = defaultdict(list)
    for iss, _ in result["accepted"]:
        if iss.milestone_title and not iss.assignee:
            p3_by_milestone[iss.milestone_title].append(iss)
    p3_sorted = sorted(p3_by_milestone.items(), key=lambda x: len(x[1]), reverse=True)

    # P2 卡片
    p2_cards = ""
    for assignee, iss_list in p2_sorted:
        items = "".join(
            f'<li><a href="https://github.com/opensourceways/backlog/issues/{iss.number}" target="_blank">'
            f'#{iss.number} {iss.title}</a></li>\n'
            for iss in iss_list
        )
        p2_cards += (
            f'<div class="card">'
            f'<h3>👤 {assignee} <span class="badge">{len(iss_list)} 条</span></h3>'
            f'<ul>{items}</ul>'
            '</div>\n'
        )

    # P3 卡片
    p3_cards = ""
    for milestone, iss_list in p3_sorted:
        items = "".join(
            f'<li><a href="https://github.com/opensourceways/backlog/issues/{iss.number}" target="_blank">'
            f'#{iss.number} {iss.title}</a></li>\n'
            for iss in iss_list
        )
        p3_cards += (
            f'<div class="card">'
            f'<h3>📅 {milestone} <span class="badge">{len(iss_list)} 条</span></h3>'
            f'<ul>{items}</ul>'
            '</div>\n'
        )

    total_action = (
        len(result["unaccepted"]) +
        sum(1 for i, _ in result["accepted"] if not i.milestone_title and not i.assignee) +
        sum(1 for i, _ in result["accepted"] if not i.milestone_title and i.assignee) +
        sum(1 for i, _ in result["accepted"] if i.milestone_title and not i.assignee)
    )

    unaccepted_rows = _html_issue_rows([i for i, _ in result["unaccepted"]])
    both_missing_rows = _html_issue_rows([i for i, _ in result["accepted"]
                                          if not i.milestone_title and not i.assignee])

    css = """
  :root {
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #c9d1d9; --text-muted: #8b949e; --accent: #58a6ff;
    --red: #f85149; --yellow: #d29922; --green: #3fb950;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.6;
    padding: 2rem; max-width: 1200px; margin: 0 auto;
  }
  h1 { font-size: 1.8rem; margin-bottom: 0.5rem; }
  h2 { font-size: 1.3rem; margin: 2rem 0 1rem; padding-bottom: 0.5rem; border-bottom: 1px solid var(--border); }
  h3 { font-size: 1rem; margin-bottom: 0.5rem; }
  .updated { color: var(--text-muted); font-size: 0.9rem; margin-bottom: 2rem; }
  .stats {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 1rem; margin-bottom: 2rem;
  }
  .stat {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; padding: 1.2rem; text-align: center;
  }
  .stat .num { font-size: 2.2rem; font-weight: 700; }
  .stat .label { color: var(--text-muted); font-size: 0.85rem; }
  .stat.red .num { color: var(--red); }
  .stat.yellow .num { color: var(--yellow); }
  .stat.green .num { color: var(--green); }
  .stat.blue .num { color: var(--accent); }
  table {
    width: 100%; border-collapse: collapse;
    background: var(--surface); border-radius: 8px; overflow: hidden;
    margin-bottom: 1.5rem;
  }
  th {
    background: #1c2128; text-align: left; padding: 0.8rem 1rem;
    font-size: 0.85rem; color: var(--text-muted); text-transform: uppercase;
    letter-spacing: 0.05em; border-bottom: 1px solid var(--border);
  }
  td { padding: 0.7rem 1rem; border-bottom: 1px solid var(--border); font-size: 0.9rem; }
  tr:last-child td { border-bottom: none; }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
  .tag {
    display: inline-block; padding: 2px 8px; border-radius: 12px;
    font-size: 0.8rem; font-weight: 600;
  }
  .tag.red { background: rgba(248,81,73,0.15); color: var(--red); }
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }
  .card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; padding: 1rem;
  }
  .card ul { list-style: none; padding: 0; }
  .card li { padding: 0.4rem 0; border-bottom: 1px solid var(--border); font-size: 0.85rem; }
  .card li:last-child { border-bottom: none; }
  .badge {
    display: inline-block; background: var(--border); color: var(--text);
    padding: 2px 10px; border-radius: 12px; font-size: 0.8rem; margin-left: 0.5rem;
  }
  .section-alert { border-left: 3px solid var(--red); padding-left: 1rem; }
  .section-warn { border-left: 3px solid var(--yellow); padding-left: 1rem; }
  @media (max-width: 768px) {
    body { padding: 1rem; }
    table { font-size: 0.8rem; }
    th, td { padding: 0.5rem; }
    .cards { grid-template-columns: 1fr; }
  }
"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PM 需求进展看板</title>
<style>{css}</style>
</head>
<body>

<h1>📋 PM 需求进展看板</h1>
<p class="updated">最后更新: {now} | 仓库: opensourceways/backlog</p>

<div class="stats">
  <div class="stat blue">
    <div class="num">{total}</div>
    <div class="label">需求总数</div>
  </div>
  <div class="stat green">
    <div class="num">{accepted_count}</div>
    <div class="label">已接受</div>
  </div>
  <div class="stat yellow">
    <div class="num">{unaccepted_count}</div>
    <div class="label">未接受</div>
  </div>
  <div class="stat red">
    <div class="num">{total_action}</div>
    <div class="label">待处理</div>
  </div>
</div>

<h2 class="section-alert">🔴 未接受需求（{unaccepted_count} 条）</h2>
<table>
  <thead><tr><th>#</th><th>标题</th><th>里程碑</th><th>责任人</th></tr></thead>
  <tbody>
{unaccepted_rows}  </tbody>
</table>

<h2 class="section-alert">🔴 已接受但缺交付时间 + 责任人</h2>
<table>
  <thead><tr><th>#</th><th>标题</th><th>里程碑</th><th>责任人</th></tr></thead>
  <tbody>
{both_missing_rows}  </tbody>
</table>

<h2 class="section-warn">🟡 P2 — 缺交付时间（按责任人聚合）</h2>
<div class="cards">
{p2_cards}</div>

<h2 class="section-warn">🟡 P3 — 缺责任人（按里程碑聚合）</h2>
<div class="cards">
{p3_cards}</div>

</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="PM 需求进展分析工具")
    parser.add_argument("--repo", default="opensourceways/backlog",
                        help="GitHub 仓库 (默认 opensourceways/backlog)")
    parser.add_argument("--state", choices=["open", "closed", "all"], default="open",
                        help="Issue 状态 (默认 open)")
    parser.add_argument("--limit", type=int, default=200,
                        help="最大拉取数量 (默认 200)")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="JSON 格式输出")
    parser.add_argument("--action", action="store_true",
                        help="只显示需要处理的 issue（行动清单）")
    parser.add_argument("--html", type=str, metavar="FILE",
                        help="生成 HTML 报告到指定文件")
    args = parser.parse_args()

    issues = fetch_issues(args.repo, args.state, args.limit)
    result = analyze(issues)

    if args.html:
        html = generate_html(result)
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"HTML 报告已生成: {args.html}", file=sys.stderr)
    elif args.action:
        print_action_items(result)
    else:
        print_dashboard(result, as_json=args.as_json)


if __name__ == "__main__":
    main()
