"""Human-readable, source-specific results without implying unavailable data exists."""

from nba_game.storage import atomic_text


def advice(error: str) -> str:
    if "HTML" in error or "403" in error:
        return "运行 --check-network，检查 Stats 代理路由，必要时切换节点后重跑。"
    if "500" in error or "502" in error or "503" in error or "超时" in error:
        return "稍后重跑同一命令补抓；当前证据不足以确定根因。"
    if "400" in error:
        return (
            "核查清单中的赛季、球队及阵容参数和上游支持范围；增加超时不会修复参数错误。"
        )
    if "429" in error:
        return "等待限流恢复后重跑，不增加请求并发。"
    if "依赖" in error:
        return "先恢复其依赖接口，再重跑以自动展开后续请求。"
    return "查看请求参数和校验结果，修复数据源或结构问题后重跑。"


def write_summary(directory, report: dict) -> None:
    counts = report.get("summary", {})
    labels = {
        "complete": "范围内采集完成",
        "partial": "部分完成",
        "running": "采集中",
        "interrupted": "已中断",
    }
    lines = [
        f"# 比赛 {report['game_id']} 数据采集",
        "",
        f"状态：{labels.get(report['status'], report['status'])}",
        "",
        "Stats 与 Live 保留各自原始结构。合法空结果表示接口未返回记录，不代表字段齐全或事件从未发生。",
        "",
        (
            f"比赛资源：{counts.get('game_resources_succeeded', 0)}/{counts.get('game_resources_expected', 0)} 返回非空数据；"
            f"球员档案：{counts.get('profiles_succeeded', 0)}/{counts.get('profiles_expected', 0)}。"
        ),
        "",
        report["profiles"]["note"],
        "",
        "|资源|状态|记录数|文件／原因|",
        "|---|---|---:|---|",
    ]
    statuses = {
        "success": "成功",
        "empty": "合法空结果",
        "failed": "失败",
        "skipped": "跳过",
    }
    for key, entry in report["resources"].items():
        detail = entry.get("error", entry.get("file", ""))
        if "file" in entry:
            detail = f"[{entry['file']}]({entry['file']})"
        lines.append(
            f"|{key}|{statuses.get(entry['status'], entry['status'])}|{entry.get('row_count', '—')}|{detail.replace('|', '/')}|"
        )
    missing = [
        (key, entry)
        for key, entry in report["resources"].items()
        if entry["status"] in ("failed", "skipped")
    ]
    if missing:
        lines += ["", "## 缺项与处理建议", ""]
        for key, entry in missing:
            lines.append(
                f"- **{key}**：{entry.get('error', '未完成')}。{advice(entry.get('error', ''))}"
            )
            if entry.get("retained_previous_file"):
                lines.append(
                    f"  旧文件保留于 `{entry['retained_previous_file']}`，不能视为本次成功结果。"
                )
    lines += ["", "## 一致性检查", ""]
    for check in report.get("checks", []):
        lines.append(
            f"- {check['name']}：{check['status']}"
            + (f"（{check['reason']}）" if check.get("reason") else "")
        )
    if not report["profiles"]["roster_complete"]:
        lines += ["", "球员名单覆盖尚不完整，请先恢复概要与传统统计。"]
    if report.get("run_error"):
        lines += ["", "运行错误：" + report["run_error"]]
    lines += [
        "",
        "## 范围边界",
        "",
        "包含约定的单场 Stats、Live、五人阵容及球员当前档案；不包含赛季／生涯背景、Synergy 汇总、视频下载、赔率及非公开逐帧追踪。",
        "",
    ]
    atomic_text(directory / "summary.md", "\n".join(lines))
