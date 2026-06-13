from __future__ import annotations

import re
from doc_checker.llm.deepseek import DeepSeekClient
from doc_checker.models import DagNode, Rule
from doc_checker.rule_agent.pdf_parser import SectionChunk
def _safe_id(title: str, i: int) -> str:
    """生成规则ID：从title中提取数字前缀+序号，如"2.8 步骤" -> "2.8.1"."""
    match = re.search(r'(\d+(?:\.\d+)*)', title)
    if match:
        prefix = match.group(1)
        return f"{prefix}.{i}"
    else:
        # 如果没有数字前缀，使用备用逻辑
        compact = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")
        compact = compact or "rule"
        return f"R-{compact}-{i:03d}"


def extract_section_rules(client: DeepSeekClient, section: SectionChunk) -> list[Rule]:
    """从单个section提取规则."""
    system_prompt = (
        "你是技术写作规范分析助手，你的任务是从一个技术文档写作规范手册中的某个章节中抽取并整理出具体、清晰的检查内容和流程。该手册针对的技术文档使用DITA (Darwin Information Typing Architecture) 标准编写。\n\n"
        "请从输入章节抽取所有的可自动检查规则，输出JSON对象：{\"rules\":[{target_object, behavior, examples, priority, complexity}]}\n\n"
        "各字段含义如下：\n"
        "- target_object：说明规则作用于哪类文档对象，例如标题、段落、表格、列表、步骤等，如果原文提及了定位对象的具体标签，必须在这里详述。例如，表格对应<table>标记对之间的内容。\n"
        "- behavior：说明对匹配到的内容**具体**做什么检查，这个检查必须是清晰、可执行的，如果有多个检查条件，请分别列出。\n"
        "- examples：若原文中有示例，保留原文中的正例、反例和说明等，如果没有则输出 null。\n"
        "- priority：表示该规则的重要程度，规则越硬性，优先级越高，在 0-10 之间。\n"
        "- complexity：表示执行该规则的成本，要检查的对象和内容越多，复杂度越高。在 0-10 之间。\n"
        "注意：\n"
        " 1. 如果该章节和规则检查无关如目录、前言等，直接返回空列表。\n"
        " 2. 如果原文提及了具体定位方式，如标记对，一定要包含在内，避免对象定位模糊。\n\n"
    )
    user_prompt = (
        f"章节标题: {section.title}\n"
        f"正文:\n{section.text[:8000]}"
    )
    raw = client.chat_json(system_prompt, user_prompt, stage="rule_extraction")
    rules_raw = raw.get("rules", [])

    rules: list[Rule] = []
    for idx, item in enumerate(rules_raw, start=1):
        rules.append(
            Rule(
                rule_id=item.get("rule_id") or _safe_id(section.title, idx),
                source_section=section.title,
                source_page=section.page_start,
                target_object=item.get("target_object", "paragraph"),
                behavior=item.get("behavior", "检查是否符合规范"),
                examples=item.get("examples", []),
                priority=int(item.get("priority", 5)),
                complexity=int(item.get("complexity", 5)),
            )
        )
    return rules


def extract_section_dag_nodes(client: DeepSeekClient, section: SectionChunk, rules: list[Rule]) -> list[DagNode]:
    """从规则生成DAG节点."""
    system_prompt = (
        "你是技术文档规则检查助手，技术文档是基于 DITA 框架，已经使用 beautifulsoup 解析完成，对象名为 soup。"
        "请从提供的规则中，构建出一个有向无环图的节点列表，每个节点都代表一个具体的操作，包括选择对象或者检查操作，并表示出这些节点的依赖关系。\n\n"
        "请输出JSON对象：{\"nodes\":[{id, type, operation, expression, prompt, depends_on}]}\n\n"
        "各字段含义如下：\n"
        "- id：自由分配的节点编号，如\"01\"。\n"
        "- type：节点类型，选择\"selector\"（选择器）或\"check\"（检查）。selector节点负责定位文档中的特定对象，由规则的target_object决定；check节点负责对selector选定的对象执行具体的检查操作。\n"
        "- title：节点标题，语言简要描述该节点的功能。如：选择文档中的所有表格。\n"
        "- rule_id：节点对应的规则ID，可对应多个规则，例如：[\"2.8.1\", \"2.8.2\"]。\n"
        "- operation：节点的操作类型。selector类节点选择\"structure\"（结构对象匹配，如表格、列表等）或\"all\"（匹配文档的所有内容，如语言风格检查类）；check类节点选择\"structure\"（结构匹配，如匹配关键词，检查标签嵌套关系等）或\"llm\"（调用大语言模型检查）。\n"
        "- expression：匹配脚本或检查脚本。当operation是structure时，提供beautifulsoup选择器和正则表达式脚本。\n"
        "- prompt：仅当type是check且operation是llm时使用。提供调用大语言模型进行检查的提示词，结合规则的behavior和examples字段。\n"
        "- depends_on：当前节点依赖的其他节点id列表，例如[\"01\", \"02\"]。表示该节点的操作需要用到这些依赖节点产生的结果。\n\n"
        "注意：\n"
        "1. 优化目标是最大化检查的效率，重复利用已有的匹配或检查结果，增加并行性。\n"
        "2. 不要出现相同或者冗余的节点。\n"
        "3. expression 只能是包括beautifulsoup和正则表达式的python代码块，可直接执行，如：soup.find_all('step', recursive=True)，不能是自然语言描述。需要包含自然语言的检查只能由 LLM 进行。\n"
    )
    
    rules_json = "\n".join(
        f"- {rule.rule_id}: target={rule.target_object}, behavior={rule.behavior}, examples={rule.examples}"
        for rule in rules
    )
    
    user_prompt = f"请根据以下规则列表构建检查DAG:\n{rules_json}"
    
    raw = client.chat_json(system_prompt, user_prompt, stage="dag_extraction")
    nodes_raw = raw.get("nodes", [])
    
    # 从section title提取前缀，用于生成node_id
    section_prefix = ""
    match = re.search(r'(\d+(?:\.\d+)*)', section.title)
    if match:
        section_prefix = match.group(1)
    
    nodes: list[DagNode] = []
    for idx, item in enumerate(nodes_raw, start=1):
        node_id = item.get("id") or f"{section_prefix}.{idx}" if section_prefix else f"{idx:02d}"
        
        node = DagNode(
            node_id=node_id,
            node_type=item.get("type", "check"),
            title=item.get("title", f"检查节点 {node_id}"),
            rule_id=item.get("rule_id"),
            operation=item.get("operation"),
            expression=item.get("expression"),
            prompt=item.get("prompt"),
            depends_on=item.get("depends_on", []),
        )
        nodes.append(node)
    
    return nodes