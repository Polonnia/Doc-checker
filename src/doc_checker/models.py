from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal


CheckMethod = Literal["regex", "keyword", "llm", "structure"]
NodeType = Literal["selector", "check"]


@dataclass
class Rule:
    rule_id: str
    source_section: str
    source_page: int | None
    target_object: str
    behavior: str
    examples: list[str] = field(default_factory=list)
    priority: int = 5
    complexity: int = 5


@dataclass
class DagNode:
    node_id: str
    node_type: NodeType
    title: str
    operation: str | None = None
    rule_id: str | None = None
    depends_on: list[str] = field(default_factory=list)
    expression: str | None = None  # beautifulsoup script
    prompt: str | None = None  # llm prompt


@dataclass
class RuleDag:
    nodes: list[DagNode]


@dataclass
class Issue:
    doc_path: str
    rule_id: str
    node_id: str
    severity: str
    message: str
    object_type: str
    object_ref: str
    evidence: str


@dataclass
class CheckReport:
    total_docs: int
    total_issues: int
    issues: list[Issue]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_docs": self.total_docs,
            "total_issues": self.total_issues,
            "issues": [asdict(i) for i in self.issues],
        }
