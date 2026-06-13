from __future__ import annotations

import json
from pathlib import Path

import typer

from doc_checker.config import ConfigError, load_config
from doc_checker.execute_agent.engine import run_check
from doc_checker.models import DagNode, RuleDag
from doc_checker.reporting import write_reports
from doc_checker.rule_agent.pipeline import build_rules_and_dag

app = typer.Typer(help="技术文档规范检查 CLI")


def _print_stage_tokens(token_usage: dict[str, dict[str, int]]) -> None:
    typer.echo("阶段 token 使用统计:")
    if not token_usage:
        typer.echo("  - 无 LLM 调用或未返回 usage")
        return

    for stage in sorted(token_usage.keys()):
        vals = token_usage[stage]
        prompt = int(vals.get("prompt_tokens", 0))
        completion = int(vals.get("completion_tokens", 0))
        total = int(vals.get("total_tokens", prompt + completion))
        typer.echo(
            f"  - {stage}: prompt={prompt}, completion={completion}, total={total}"
        )


def _load_dag(path: Path) -> RuleDag:
    raw = json.loads(path.read_text(encoding="utf-8"))
    nodes = [DagNode(**n) for n in raw.get("nodes", [])]
    return RuleDag(nodes=nodes)


@app.command("build-rules")
def build_rules(config: str = typer.Option("config.yaml", help="配置文件路径")) -> None:
    try:
        cfg = load_config(config)
        rules_path, dag_path, dag, token_usage = build_rules_and_dag(cfg)
        typer.echo(f"规则已生成: {rules_path}")
        typer.echo(f"DAG已生成: {dag_path}")
        typer.echo(f"节点数量: {len(dag.nodes)}")
        _print_stage_tokens(token_usage)
    except ConfigError as exc:
        typer.echo(f"配置错误: {exc}")
        raise typer.Exit(code=2)


@app.command("run-check")
def run_check_only(
    config: str = typer.Option("config.yaml", help="配置文件路径"),
    dag: str = typer.Option(..., help="DAG文件路径"),
) -> None:
    try:
        cfg = load_config(config)
        dag_obj = _load_dag(Path(dag))
        report, token_usage = run_check(cfg, dag_obj)
        json_path, md_path = write_reports(report, cfg.paths.output_dir)
        typer.echo(f"JSON报告: {json_path}")
        typer.echo(f"Markdown报告: {md_path}")
        typer.echo(f"问题总数: {report.total_issues}")
        _print_stage_tokens(token_usage)
    except ConfigError as exc:
        typer.echo(f"配置错误: {exc}")
        raise typer.Exit(code=2)


@app.command("full-run")
def full_run(config: str = typer.Option("config.yaml", help="配置文件路径")) -> None:
    try:
        cfg = load_config(config)
        _, dag_path, dag, build_tokens = build_rules_and_dag(cfg)
        report, check_tokens = run_check(cfg, dag)
        json_path, md_path = write_reports(report, cfg.paths.output_dir)
        typer.echo(f"DAG文件: {dag_path}")
        typer.echo(f"JSON报告: {json_path}")
        typer.echo(f"Markdown报告: {md_path}")
        typer.echo(f"文档数量: {report.total_docs}, 问题总数: {report.total_issues}")
        merged_tokens: dict[str, dict[str, int]] = {}
        for stage_map in (build_tokens, check_tokens):
            for stage, vals in stage_map.items():
                if stage not in merged_tokens:
                    merged_tokens[stage] = {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                    }
                merged_tokens[stage]["prompt_tokens"] += int(vals.get("prompt_tokens", 0))
                merged_tokens[stage]["completion_tokens"] += int(vals.get("completion_tokens", 0))
                merged_tokens[stage]["total_tokens"] += int(vals.get("total_tokens", 0))
        _print_stage_tokens(merged_tokens)
    except ConfigError as exc:
        typer.echo(f"配置错误: {exc}")
        raise typer.Exit(code=2)


if __name__ == "__main__":
    app()
