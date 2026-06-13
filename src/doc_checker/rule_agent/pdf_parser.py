from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz


@dataclass
class SectionChunk:
    title: str
    level: int
    page_start: int
    page_end: int
    text: str


def parse_pdf_sections(pdf_path: Path) -> list[SectionChunk]:
    doc = fitz.open(pdf_path)
    toc = doc.get_toc(simple=True)

    if not toc:
        full_text = "\n".join(page.get_text("text") for page in doc)
        return [
            SectionChunk(
                title="全文",
                level=1,
                page_start=1,
                page_end=doc.page_count,
                text=full_text,
            )
        ]

    chunks: list[SectionChunk] = []
    for idx, (level, title, page_start) in enumerate(toc):
        if idx + 1 < len(toc) and toc[idx + 1][0] > level:
            continue
        
        page_end = doc.page_count
        for j in range(idx + 1, len(toc)):
            next_level, _, next_page = toc[j]
            if next_level <= level:
                page_end = next_page - 1
                break

        pages = [doc[pno - 1].get_text("text") for pno in range(page_start, max(page_start, page_end) + 1)]
        chunk_text = "\n".join(pages).strip()
        if chunk_text:
            chunks.append(
                SectionChunk(
                    title=title.strip(),
                    level=level,
                    page_start=page_start,
                    page_end=page_end,
                    text=chunk_text,
                )
            )
    return chunks
