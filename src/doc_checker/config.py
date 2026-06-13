from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class PathsConfig:
    rule_pdf: Path
    sample_xml_dir: Path
    output_dir: Path


@dataclass
class DeepSeekConfig:
    base_url: str
    model: str
    api_key: str
    timeout_seconds: int
    max_retries: int


@dataclass
class ExecutionConfig:
    max_workers: int
    skip_llm_when_no_key: bool
    low_cost_methods_first: list[str]
    llm_prescreen_keywords: list[str]


@dataclass
class AppConfig:
    project_name: str
    paths: PathsConfig
    deepseek: DeepSeekConfig
    execution: ExecutionConfig


class ConfigError(Exception):
    pass


def _require(data: dict[str, Any], key: str) -> Any:
    if key not in data:
        raise ConfigError(f"Missing required config key: {key}")
    return data[key]


def load_config(config_path: str | Path) -> AppConfig:
    cfg_path = Path(config_path)
    if not cfg_path.exists():
        raise ConfigError(f"Config file not found: {cfg_path}")

    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

    project = raw.get("project", {})
    paths_raw = _require(raw, "paths")
    deepseek_raw = _require(raw, "deepseek")
    execution_raw = _require(raw, "execution")

    root = cfg_path.parent

    paths = PathsConfig(
        rule_pdf=(root / _require(paths_raw, "rule_pdf")).resolve(),
        sample_xml_dir=(root / _require(paths_raw, "sample_xml_dir")).resolve(),
        output_dir=(root / _require(paths_raw, "output_dir")).resolve(),
    )

    deepseek = DeepSeekConfig(
        base_url=_require(deepseek_raw, "base_url"),
        model=_require(deepseek_raw, "model"),
        api_key=_require(deepseek_raw, "api_key"),
        timeout_seconds=int(deepseek_raw.get("timeout_seconds", 60)),
        max_retries=int(deepseek_raw.get("max_retries", 2)),
    )

    execution = ExecutionConfig(
        max_workers=int(execution_raw.get("max_workers", 8)),
        skip_llm_when_no_key=bool(execution_raw.get("skip_llm_when_no_key", True)),
        low_cost_methods_first=list(execution_raw.get("low_cost_methods_first", ["regex", "keyword", "structure"])),
        llm_prescreen_keywords=list(execution_raw.get("llm_prescreen_keywords", [])),
    )

    app = AppConfig(
        project_name=project.get("name", "doc-rule-checker"),
        paths=paths,
        deepseek=deepseek,
        execution=execution,
    )

    validate_config(app)
    return app


def validate_config(cfg: AppConfig) -> None:
    if not cfg.paths.rule_pdf.exists():
        raise ConfigError(f"Rule PDF not found: {cfg.paths.rule_pdf}")
    if not cfg.paths.sample_xml_dir.exists():
        raise ConfigError(f"Sample XML directory not found: {cfg.paths.sample_xml_dir}")
    cfg.paths.output_dir.mkdir(parents=True, exist_ok=True)
