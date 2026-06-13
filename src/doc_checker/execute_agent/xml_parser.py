from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET


@dataclass
class DocumentObjects:
    path: Path
    headings: list[str]
    paragraphs: list[str]
    sentences: list[str]
    tables: list[dict[str, int]]
    lists: list[str]
    raw_text: str


def _extract_texts(root: ET.Element, tag_keywords: list[str]) -> list[str]:
    out: list[str] = []
    for elem in root.iter():
        tag = (elem.tag or "").lower()
        if any(k in tag for k in tag_keywords):
            txt = "".join(elem.itertext()).strip()
            if txt:
                out.append(txt)
    return out


def parse_xml_document(path: Path) -> DocumentObjects:
    tree = ET.parse(path)
    root = tree.getroot()

    headings = _extract_texts(root, ["title", "heading", "h1", "h2", "h3"])
    paragraphs = _extract_texts(root, ["p", "para", "paragraph", "text"])

    raw_text = "\n".join(t.strip() for t in root.itertext() if t and t.strip())
    sentences = [s.strip() for s in raw_text.replace("\n", "。").split("。") if s.strip()]

    tables: list[dict[str, int]] = []
    for tbl in root.iter():
        tag = (tbl.tag or "").lower()
        if "table" in tag:
            rows = [child for child in tbl.iter() if "row" in (child.tag or "").lower()]
            row_count = len(rows)
            col_count = 0
            for row in rows:
                cols = [c for c in row if "cell" in (c.tag or "").lower() or "col" in (c.tag or "").lower()]
                col_count = max(col_count, len(cols))
            tables.append({"rows": row_count, "cols": col_count})

    lists = _extract_texts(root, ["list", "item", "li"])

    return DocumentObjects(
        path=path,
        headings=headings,
        paragraphs=paragraphs,
        sentences=sentences,
        tables=tables,
        lists=lists,
        raw_text=raw_text,
    )


def collect_xml_documents(xml_dir: Path) -> list[DocumentObjects]:
    docs: list[DocumentObjects] = []
    for p in sorted(xml_dir.glob("*.xml")):
        try:
            docs.append(parse_xml_document(p))
        except Exception:
            continue
    return docs
