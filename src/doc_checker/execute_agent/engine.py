from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from doc_checker.config import AppConfig
from doc_checker.execute_agent.xml_parser import DocumentObjects, collect_xml_documents
from doc_checker.llm.deepseek import DeepSeekClient
from doc_checker.models import CheckReport, DagNode, Issue, RuleDag


def _severity_from_priority(priority: int) -> str:
    if priority >= 8:
        return "high"
    if priority >= 5:
        return "medium"
    return "low"


def _select_objects(doc: DocumentObjects, target: str) -> list[tuple[str, str]]:
    if target == "heading":
        return [(f"heading:{i+1}", x) for i, x in enumerate(doc.headings)]
    if target == "paragraph":
        return [(f"paragraph:{i+1}", x) for i, x in enumerate(doc.paragraphs)]
    if target == "sentence":
        return [(f"sentence:{i+1}", x) for i, x in enumerate(doc.sentences)]
    if target == "table":
        return [(f"table:{i+1}", str(x)) for i, x in enumerate(doc.tables)]
    if target == "list":
        return [(f"list:{i+1}", x) for i, x in enumerate(doc.lists)]
    return [("raw:1", doc.raw_text)]


def _run_regex_check(node: DagNode, doc: DocumentObjects, selected: list[tuple[str, str]]) -> list[Issue]:
    import re

    pattern = node.payload.get("regex_pattern")
    if not pattern:
        return []

    issues: list[Issue] = []
    sev = _severity_from_priority(int(node.payload.get("priority", 5)))
    for ref, text in selected:
        if not re.match(pattern, text):
            issues.append(
                Issue(
                    doc_path=str(doc.path),
                    rule_id=node.rule_id or "unknown",
                    node_id=node.node_id,
                    severity=sev,
                    message=f"内容不符合正则规则: {pattern}",
                    object_type=node.target_object or "unknown",
                    object_ref=ref,
                    evidence=text[:200],
                )
            )
    return issues


def _run_keyword_check(node: DagNode, doc: DocumentObjects, selected: list[tuple[str, str]]) -> list[Issue]:
    keywords: list[str] = list(node.payload.get("keywords", []))
    if not keywords:
        return []

    issues: list[Issue] = []
    sev = _severity_from_priority(int(node.payload.get("priority", 5)))
    for ref, text in selected:
        hits = [k for k in keywords if k in text]
        if hits:
            issues.append(
                Issue(
                    doc_path=str(doc.path),
                    rule_id=node.rule_id or "unknown",
                    node_id=node.node_id,
                    severity=sev,
                    message=f"命中关键词: {', '.join(hits)}",
                    object_type=node.target_object or "unknown",
                    object_ref=ref,
                    evidence=text[:200],
                )
            )
    return issues


def _run_structure_check(node: DagNode, doc: DocumentObjects, selected: list[tuple[str, str]]) -> list[Issue]:
    issues: list[Issue] = []
    sev = _severity_from_priority(int(node.payload.get("priority", 5)))

    if node.target_object == "table":
        for i, table in enumerate(doc.tables, start=1):
            rows = int(table.get("rows", 0))
            cols = int(table.get("cols", 0))
            if rows < 2 or cols < 2:
                issues.append(
                    Issue(
                        doc_path=str(doc.path),
                        rule_id=node.rule_id or "unknown",
                        node_id=node.node_id,
                        severity=sev,
                        message="表格不满足至少2行2列",
                        object_type="table",
                        object_ref=f"table:{i}",
                        evidence=f"rows={rows}, cols={cols}",
                    )
                )
    return issues


def _run_llm_check(
    node: DagNode,
    doc: DocumentObjects,
    selected: list[tuple[str, str]],
    client: DeepSeekClient,
    prescreen_keywords: list[str],
) -> list[Issue]:
    if not selected:
        return []

    # First-stage prescreen to reduce expensive LLM calls.
    narrowed = selected
    if prescreen_keywords:
        narrowed = [(ref, text) for ref, text in selected if any(k in text for k in prescreen_keywords)]
        if not narrowed:
            return []

    if not client.enabled:
        return []

    sev = _severity_from_priority(int(node.payload.get("priority", 5)))
    issues: list[Issue] = []

    system_prompt = (
        "你是技术文档规范检查助手。"
        "你会判断输入文本是否违反指定规则，输出JSON对象："
        "{\"violation\": true/false, \"reason\": \"...\"}"
    )

    for ref, text in narrowed[:50]:
        user_prompt = (
            f"规则ID: {node.rule_id}\n"
            f"对象类型: {node.target_object}\n"
            f"规则描述: {node.title}\n"
            f"待检查文本:\n{text[:1200]}"
        )
        try:
            result = client.chat_json(system_prompt, user_prompt, stage="check_execution")
        except Exception:
            continue

        if bool(result.get("violation", False)):
            issues.append(
                Issue(
                    doc_path=str(doc.path),
                    rule_id=node.rule_id or "unknown",
                    node_id=node.node_id,
                    severity=sev,
                    message=result.get("reason", "LLM判定存在问题"),
                    object_type=node.target_object or "unknown",
                    object_ref=ref,
                    evidence=text[:200],
                )
            )

    return issues


def _topo_layers(nodes: list[DagNode]) -> list[list[DagNode]]:
    idx = {n.node_id: n for n in nodes}
    indeg = {n.node_id: len(n.depends_on) for n in nodes}
    succ: dict[str, list[str]] = {n.node_id: [] for n in nodes}

    for n in nodes:
        for d in n.depends_on:
            succ.setdefault(d, []).append(n.node_id)

    current = [idx[nid] for nid, deg in indeg.items() if deg == 0]
    layers: list[list[DagNode]] = []

    while current:
        layers.append(current)
        next_ids: list[str] = []
        for n in current:
            for x in succ.get(n.node_id, []):
                indeg[x] -= 1
                if indeg[x] == 0:
                    next_ids.append(x)
        current = [idx[nid] for nid in next_ids]

    return layers


def _sort_check_nodes(nodes: list[DagNode], low_cost: list[str]) -> list[DagNode]:
    rank = {m: i for i, m in enumerate(low_cost)}
    return sorted(nodes, key=lambda n: rank.get(n.method, 99))


def run_check(cfg: AppConfig, dag: RuleDag) -> tuple[CheckReport, dict[str, dict[str, int]]]:
    docs = collect_xml_documents(cfg.paths.sample_xml_dir)
    client = DeepSeekClient(cfg.deepseek)

    node_map = {n.node_id: n for n in dag.nodes}
    layers = _topo_layers(dag.nodes)
    all_issues: list[Issue] = []

    for doc in docs:
        selected_cache: dict[str, list[tuple[str, str]]] = {}
        skipped_selectors: set[str] = set()

        for layer in layers:
            layer_checks = [n for n in layer if n.node_type == "check"]
            layer_checks = _sort_check_nodes(layer_checks, cfg.execution.low_cost_methods_first)

            # First pass: prepare selector caches and prune empty branches.
            for chk in layer_checks:
                selector_id = chk.depends_on[0] if chk.depends_on else ""
                selector = node_map.get(selector_id)
                if not selector or selector.node_type != "selector":
                    continue
                if selector_id not in selected_cache:
                    selected_cache[selector_id] = _select_objects(doc, selector.target_object or "raw")
                if not selected_cache[selector_id]:
                    skipped_selectors.add(selector_id)

            futures = []
            with ThreadPoolExecutor(max_workers=cfg.execution.max_workers) as pool:
                for chk in layer_checks:
                    selector_id = chk.depends_on[0] if chk.depends_on else ""
                    if selector_id in skipped_selectors:
                        continue
                    selected = selected_cache.get(selector_id, [])

                    # 优先使用operation字段（新的DAG节点），否则使用method字段（向后兼容）
                    check_method = chk.operation or chk.method
                    
                    if check_method == "regex":
                        futures.append(pool.submit(_run_regex_check, chk, doc, selected))
                    elif check_method == "keyword":
                        futures.append(pool.submit(_run_keyword_check, chk, doc, selected))
                    elif check_method == "structure":
                        futures.append(pool.submit(_run_structure_check, chk, doc, selected))
                    else:
                        futures.append(
                            pool.submit(
                                _run_llm_check,
                                chk,
                                doc,
                                selected,
                                client,
                                cfg.execution.llm_prescreen_keywords,
                            )
                        )

                for fut in as_completed(futures):
                    try:
                        all_issues.extend(fut.result())
                    except Exception:
                        continue

    all_issues.sort(key=lambda x: (x.doc_path, x.severity, x.rule_id, x.object_ref))

    report = CheckReport(
        total_docs=len(docs),
        total_issues=len(all_issues),
        issues=all_issues,
    )
    return report, client.get_stage_tokens()
