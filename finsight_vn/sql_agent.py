"""Small deterministic and read-only SQL agent for the interview MVP."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Sequence


APPROVED_RELATION = "analytics.mart_regular_company_quarterly"
SUPPORTED_SYMBOLS = ("FPT", "HPG", "MWG", "VNM")
PERIOD_RE = re.compile(r"\b(20\d{2})\s*Q([1-4])\b", re.IGNORECASE)
BLOCKED_SQL_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|COPY|CALL|DO)\b",
    re.IGNORECASE,
)


class AgentQuestionError(ValueError):
    """Raised when a question is outside the intentionally small MVP grammar."""


class UnsafeSqlError(ValueError):
    """Raised when generated or supplied SQL violates the read-only contract."""


@dataclass(frozen=True)
class AgentResponse:
    question: str
    answer: str
    sql: str
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]


def _symbols(question: str) -> list[str]:
    upper = question.upper()
    return [symbol for symbol in SUPPORTED_SYMBOLS if re.search(rf"\b{symbol}\b", upper)]


def _periods(question: str) -> list[str]:
    return [f"{year}Q{quarter}" for year, quarter in PERIOD_RE.findall(question)]


def _sql_list(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def generate_sql(question: str) -> str:
    """Translate supported financial questions into auditable SQL templates."""
    normalized = " ".join(question.strip().split())
    lower = normalized.lower()
    symbols = _symbols(normalized)
    periods = _periods(normalized)
    if not symbols:
        raise AgentQuestionError(
            "Name at least one supported company: FPT, HPG, MWG, or VNM."
        )

    relation = APPROVED_RELATION
    if "operating cash flow" in lower:
        if len(symbols) != 1 or len(periods) != 2:
            raise AgentQuestionError(
                "Operating cash-flow questions require one company and a start/end quarter."
            )
        start, end = sorted(periods)
        return (
            "SELECT symbol, period, operating_cash_flow\n"
            f"FROM {relation}\n"
            f"WHERE symbol = '{symbols[0]}' AND period BETWEEN '{start}' AND '{end}'\n"
            "ORDER BY fiscal_year, fiscal_quarter"
        )

    if "gross margin" in lower:
        if len(symbols) != 1 or len(periods) != 1:
            raise AgentQuestionError("Gross-margin questions require one company and one quarter.")
        return (
            "SELECT symbol, period, gross_margin\n"
            f"FROM {relation}\n"
            f"WHERE symbol = '{symbols[0]}' AND period = '{periods[0]}'"
        )

    if "net profit" in lower and ("yoy" in lower or "grow" in lower):
        if len(symbols) != 1 or len(periods) != 1:
            raise AgentQuestionError("Net-profit growth requires one company and one quarter.")
        return (
            "SELECT symbol, period, net_profit, net_profit_yoy_growth\n"
            f"FROM {relation}\n"
            f"WHERE symbol = '{symbols[0]}' AND period = '{periods[0]}'"
        )

    if "revenue" in lower and ("growth" in lower or "grow" in lower):
        if len(periods) != 1:
            raise AgentQuestionError("Revenue-growth questions require one quarter.")
        return (
            "SELECT symbol, period, revenue, revenue_yoy_growth\n"
            f"FROM {relation}\n"
            f"WHERE symbol IN ({_sql_list(symbols)}) AND period = '{periods[0]}'\n"
            "ORDER BY revenue_yoy_growth DESC NULLS LAST, symbol"
        )

    if "revenue" in lower:
        if len(symbols) != 1 or not periods:
            raise AgentQuestionError("Revenue questions require one company and at least one quarter.")
        if len(periods) == 1:
            predicate = f"period = '{periods[0]}'"
        else:
            predicate = f"period IN ({_sql_list(periods)})"
        return (
            "SELECT symbol, period, revenue\n"
            f"FROM {relation}\n"
            f"WHERE symbol = '{symbols[0]}' AND {predicate}\n"
            "ORDER BY fiscal_year, fiscal_quarter"
        )

    raise AgentQuestionError(
        "Supported intents are revenue, revenue growth, net-profit growth, gross margin, "
        "and operating cash flow."
    )


def validate_read_only_sql(sql: str) -> None:
    """Allow a single SELECT against only the approved analytical mart."""
    cleaned = sql.strip()
    if not re.match(r"^(SELECT|WITH)\b", cleaned, re.IGNORECASE):
        raise UnsafeSqlError("Only SELECT or WITH queries are allowed.")
    if ";" in cleaned or "--" in cleaned or "/*" in cleaned:
        raise UnsafeSqlError("Multiple statements and SQL comments are not allowed.")
    if BLOCKED_SQL_RE.search(cleaned):
        raise UnsafeSqlError("Mutation and DDL statements are blocked.")
    relations = re.findall(r"\b(?:FROM|JOIN)\s+([a-zA-Z_][\w.]*)", cleaned, re.IGNORECASE)
    if not relations or any(relation.lower() != APPROVED_RELATION for relation in relations):
        raise UnsafeSqlError(f"Queries may access only {APPROVED_RELATION}.")


def execute_postgres(dsn: str, sql: str) -> tuple[tuple[str, ...], tuple[tuple[Any, ...], ...]]:
    import psycopg

    validate_read_only_sql(sql)
    with psycopg.connect(dsn) as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        connection.execute("SET LOCAL statement_timeout = '5s'")
        with connection.cursor() as cursor:
            cursor.execute(sql)
            columns = tuple(column.name for column in cursor.description or ())
            rows = tuple(cursor.fetchmany(200))
        connection.rollback()
    return columns, rows


def _display(value: Any) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float):
        return f"{value:,.2%}" if -5 <= value <= 5 else f"{value:,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def summarize(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    if not rows:
        return "No matching financial data is available for the requested scope."
    rendered = []
    for row in rows:
        values = dict(zip(columns, row))
        prefix = f"{values.get('symbol', '')} {values.get('period', '')}".strip()
        measures = [
            f"{name.replace('_', ' ')}={_display(value)}"
            for name, value in values.items()
            if name not in {"symbol", "period"}
        ]
        rendered.append(f"{prefix}: " + ", ".join(measures))
    return "; ".join(rendered)


def ask(
    question: str,
    dsn: str,
    executor: Callable[[str, str], tuple[tuple[str, ...], tuple[tuple[Any, ...], ...]]] = execute_postgres,
) -> AgentResponse:
    sql = generate_sql(question)
    validate_read_only_sql(sql)
    columns, rows = executor(dsn, sql)
    return AgentResponse(question, summarize(columns, rows), sql, columns, rows)
