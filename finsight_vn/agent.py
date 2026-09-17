"""Unified deterministic router for the SQL and document RAG branches."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from finsight_vn.rag import LocalVectorIndex, RagResponse, grounded_answer
from finsight_vn.sql_agent import AgentResponse, ask as ask_sql, execute_postgres


SQL_TERMS = (
    "revenue", "gross margin", "net margin", "net profit", "operating cash flow",
    "doanh thu", "biên lợi nhuận", "lợi nhuận", "lưu chuyển tiền",
)
RAG_TERMS = (
    "report", "discuss", "say about", "explain", "risk", "policy", "note",
    "financial statement", "báo cáo", "thuyết minh", "rủi ro", "chính sách",
    "trình bày", "cơ sở", "khoản vay", "đầu tư", "related party",
)
PERIOD_RE = re.compile(r"\b20\d{2}Q[1-4]\b", re.IGNORECASE)


class HybridQuestionError(ValueError):
    pass


@dataclass(frozen=True)
class FinSightResponse:
    route: str
    sql: AgentResponse | None = None
    rag: RagResponse | None = None

    @property
    def answer(self) -> str:
        if self.sql:
            return self.sql.answer
        if self.rag:
            return self.rag.answer
        return ""


def route_question(question: str) -> str:
    lower = " ".join(question.casefold().split())
    has_sql = any(term in lower for term in SQL_TERMS) and bool(PERIOD_RE.search(question))
    has_rag = any(term in lower for term in RAG_TERMS)
    if has_sql and has_rag:
        return "HYBRID"
    if has_sql:
        return "SQL"
    return "RAG"


def infer_symbol(question: str) -> str | None:
    upper = question.upper()
    return next((symbol for symbol in ("FPT", "HPG", "MWG", "VNM") if re.search(rf"\b{symbol}\b", upper)), None)


def infer_period(question: str) -> str | None:
    match = PERIOD_RE.search(question)
    return match.group(0).upper() if match else None


def ask(
    question: str,
    *,
    dsn: str | None,
    index_path: str | Path,
    top_k: int = 5,
    sql_executor: Callable[[str, str], tuple[tuple[str, ...], tuple[tuple[Any, ...], ...]]] = execute_postgres,
) -> FinSightResponse:
    route = route_question(question)
    if route == "HYBRID":
        raise HybridQuestionError(
            "Hybrid SQL + RAG synthesis is not implemented in this MVP. Ask the structured and document questions separately."
        )
    if route == "SQL":
        if not dsn:
            raise ValueError("FINSIGHT_DATABASE_URL is required for SQL questions.")
        return FinSightResponse("SQL", sql=ask_sql(question, dsn, executor=sql_executor))
    index = LocalVectorIndex.load(index_path)
    rag = grounded_answer(
        question, index, symbol=infer_symbol(question), period=infer_period(question), top_k=top_k
    )
    return FinSightResponse("RAG", rag=rag)
