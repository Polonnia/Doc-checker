from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from doc_checker.models import CheckReport


def write_reports(report: CheckReport, output_dir: Path) -> tuple[Path, Path]:
    json_path = output_dir / "check_report.json"
    md_path = output_dir / "check_report.md"

    json_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines: list[str] = []
    lines.append("# 规范检查报告")
    lines.append("")
    lines.append(f"- 文档数量: {report.total_docs}")
    lines.append(f"- 问题总数: {report.total_issues}")
    lines.append("")
    lines.append("## 问题明细")
    lines.append("")

    if not report.issues:
        lines.append("未发现问题。")
    else:
        for idx, issue in enumerate(report.issues, start=1):
            lines.append(f"### {idx}. [{issue.severity}] {issue.rule_id}")
            lines.append(f"- 文档: {issue.doc_path}")
            lines.append(f"- 对象: {issue.object_type}")
            lines.append(f"- 位置: {issue.object_ref}")
            lines.append(f"- 描述: {issue.message}")
            lines.append(f"- 证据: {issue.evidence}")
            lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path
