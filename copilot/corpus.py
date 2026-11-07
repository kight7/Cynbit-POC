"""Load the 13 Cynbit case-study markdown files and turn them into retrievable chunks.

Chunking strategy:
  * one chunk per evidence section (Client need, Challenge, Solution, Tech stack, Outcome / metric)
  * plus one "summary" chunk per case that combines title, industry, solution and outcome

Sections that are speculation by *this project* ("AI/ML opportunity", "Source notes") are
deliberately NOT indexed, so the proposal generator can never cite them as Cynbit's delivered work.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .config import CASE_STUDY_DIR
from .schemas import Chunk

INDEXED_SECTIONS = ["Client need", "Challenge", "Solution", "Tech stack", "Outcome / metric"]

# Map the free-text industry line of each case to the shared taxonomy keys.
INDUSTRY_MAP = {
    "healthcare": "healthcare",
    "fintech": "fintech",
    "payments": "fintech",
    "e-commerce": "ecommerce_retail",
    "retail": "ecommerce_retail",
    "fashion": "fashion",
    "marketing": "marketing_adtech",
    "adtech": "marketing_adtech",
    "edtech": "edtech",
    "entertainment": "entertainment_events",
    "events": "entertainment_events",
    "enterprise software": "enterprise_software",
    "saas": "saas_collaboration",
    "collaboration": "saas_collaboration",
    "food": "food_supply_chain",
    "supply chain": "food_supply_chain",
}


@dataclass
class CaseStudy:
    case_id: str
    title: str
    client: str
    industry_raw: str
    industries: list[str]
    solution_type: str
    source_url: str
    sections: dict[str, str]
    metrics: list[str] = field(default_factory=list)

    @property
    def primary_industry(self) -> str:
        return self.industries[0] if self.industries else "other"


def _clean(text: str) -> str:
    # Strip markdown bold and collapse whitespace; keep bullet structure readable.
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _map_industries(raw: str) -> list[str]:
    out: list[str] = []
    for part in re.split(r"[,/]", raw.lower()):
        part = part.strip()
        for key, val in INDUSTRY_MAP.items():
            if key in part and val not in out:
                out.append(val)
    return out


def parse_case_file(path: Path) -> CaseStudy:
    raw = path.read_text(encoding="utf-8")
    num = re.match(r"(\d+)", path.name).group(1)
    case_id = f"CS-{int(num):02d}"

    title = re.search(r"^#\s+(.+)$", raw, re.M).group(1).strip()

    def meta(label: str) -> str:
        m = re.search(rf"^- \*\*{re.escape(label)}:\*\*\s*(.+)$", raw, re.M)
        return m.group(1).strip() if m else ""

    sections: dict[str, str] = {}
    for m in re.finditer(r"^##\s+(.+?)\s*\n(.*?)(?=^##\s|\Z)", raw, re.M | re.S):
        sections[m.group(1).strip()] = _clean(m.group(2))

    metrics = []
    for line in sections.get("Outcome / metric", "").splitlines():
        line = line.strip("- ").strip()
        # Keep only quantified outcomes (contain a digit) as "citable metrics".
        if line and re.search(r"\d", line):
            metrics.append(re.sub(r"\s*\((?:Cynbit|draft)[^)]*\)\s*$", "", line))

    industry_raw = meta("Industry")
    return CaseStudy(
        case_id=case_id,
        title=title,
        client=meta("Name listed by Cynbit"),
        industry_raw=industry_raw,
        industries=_map_industries(industry_raw),
        solution_type=meta("Solution type"),
        source_url=meta("Source URL"),
        sections=sections,
        metrics=metrics,
    )


@lru_cache(maxsize=1)
def load_case_studies(directory: str | None = None) -> tuple[CaseStudy, ...]:
    d = Path(directory) if directory else CASE_STUDY_DIR
    files = sorted(d.glob("[0-9][0-9]-*.md"))
    if not files:
        raise FileNotFoundError(f"No case-study markdown files found in {d}")
    return tuple(parse_case_file(f) for f in files)


def case_by_id() -> dict[str, CaseStudy]:
    return {c.case_id: c for c in load_case_studies()}


def build_chunks(cases: tuple[CaseStudy, ...] | None = None) -> list[Chunk]:
    cases = cases or load_case_studies()
    chunks: list[Chunk] = []
    for c in cases:
        base_meta = {
            "case_id": c.case_id,
            "title": c.title,
            "client": c.client,
            "industry": c.primary_industry,
            "industries": ",".join(c.industries),
            "solution_type": c.solution_type,
            "source_url": c.source_url,
            "metric": "; ".join(c.metrics),
        }
        header = f"{c.title} ({c.client}; {c.industry_raw})"
        for sec in INDEXED_SECTIONS:
            body = c.sections.get(sec, "").strip()
            if not body:
                continue
            if sec == "Tech stack":
                body = body.replace("Inferred stack (draft):", "Inferred stack (not confirmed by Cynbit):")
            slug = sec.lower().replace(" / ", "_").replace(" ", "_")
            chunks.append(
                Chunk(
                    chunk_id=f"{c.case_id}::{slug}",
                    case_id=c.case_id,
                    section=sec,
                    text=f"{header}\n{sec}: {body}",
                    metadata={**base_meta, "section": sec},
                )
            )
        summary = (
            f"{header}\nSolution type: {c.solution_type}\n"
            f"Need: {c.sections.get('Client need', '')}\n"
            f"Solution: {c.sections.get('Solution', '')}\n"
            f"Outcome: {'; '.join(c.metrics) or c.sections.get('Outcome / metric', '')}"
        )
        chunks.append(
            Chunk(
                chunk_id=f"{c.case_id}::summary",
                case_id=c.case_id,
                section="Summary",
                text=summary,
                metadata={**base_meta, "section": "Summary"},
            )
        )
    return chunks
