from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path
import logging

from doc_checker.config import AppConfig
from doc_checker.llm.deepseek import DeepSeekClient
from doc_checker.models import RuleDag
from doc_checker.rule_agent.pdf_parser import parse_pdf_sections
from doc_checker.rule_agent.extractor import extract_section_rules, extract_section_dag_nodes

write_lock = asyncio.Lock()

# 全局写入锁
write_lock = asyncio.Lock()

async def process_section_with_writing(
    client: DeepSeekClient,
    section,
    rules_path: Path,
    dag_path: Path,
    section_index: int,
    total_sections: int
) -> tuple[list, list]:
    """处理单个章节：提取规则，生成DAG节点，并立即写入文件。"""
    logging.info(f"Processing section {section_index}/{total_sections}: {section.title}")
    
    # 提取规则
    rules = await asyncio.to_thread(extract_section_rules, client, section)
    
    # 立即写入规则
    if rules:
        rules_data = [asdict(rule) for rule in rules]
        async with write_lock:
            existing_rules = []
            if rules_path.exists():
                try:
                    with open(rules_path, 'r', encoding='utf-8') as f:
                        existing_rules = json.load(f)
                except json.JSONDecodeError:
                    existing_rules = []
            
            existing_rules.extend(rules_data)
            with open(rules_path, 'w', encoding='utf-8') as f:
                json.dump(existing_rules, f, ensure_ascii=False, indent=2)
            logging.info(f"  written {len(rules)} rules to {rules_path}")
    
    # 生成DAG节点并立即写入
    nodes = await asyncio.to_thread(extract_section_dag_nodes, client, section, rules)
    
    if nodes:
        nodes_data = [asdict(node) for node in nodes]
        async with write_lock:
            existing_nodes = []
            if dag_path.exists():
                try:
                    with open(dag_path, 'r', encoding='utf-8') as f:
                        existing_nodes = json.load(f).get("nodes", [])
                except json.JSONDecodeError:
                    existing_nodes = []
            
            existing_nodes.extend(nodes_data)
            dag_payload = {"nodes": existing_nodes}
            with open(dag_path, 'w', encoding='utf-8') as f:
                json.dump(dag_payload, f, ensure_ascii=False, indent=2)
            logging.info(f"  written {len(nodes)} nodes to {dag_path}")
    
    return rules, nodes

async def async_build_rules_and_dag(cfg: AppConfig) -> tuple[Path, Path, RuleDag, dict[str, dict[str, int]]]:
    """异步构建规则和DAG，每个章节处理完后立即写入JSON文件。"""
    sections = parse_pdf_sections(cfg.paths.rule_pdf)
    client = DeepSeekClient(cfg.deepseek)
    
    rules_path = cfg.paths.output_dir / "rules.json"
    dag_path = cfg.paths.output_dir / "rule_dag.json"
    
    # 清空文件
    rules_path.write_text("[]", encoding="utf-8")
    dag_path.write_text('{"nodes": []}', encoding="utf-8")
    
    # 并行处理所有章节
    tasks = [
        process_section_with_writing(
            client, section, rules_path, dag_path, idx, len(sections)
        )
        for idx, section in enumerate(sections, start=1)
    ]
    
    results = await asyncio.gather(*tasks)
    
    # 收集所有结果
    all_rules = []
    all_nodes = []
    for rules, nodes in results:
        all_rules.extend(rules)
        all_nodes.extend(nodes)
    
    dag = RuleDag(nodes=all_nodes)
    return rules_path, dag_path, dag, client.get_stage_tokens()

def build_rules_and_dag(cfg: AppConfig) -> tuple[Path, Path, RuleDag, dict[str, dict[str, int]]]:
    """同步入口：构建规则和DAG，每个章节完成后立即写入JSON。"""
    return asyncio.run(async_build_rules_and_dag(cfg))