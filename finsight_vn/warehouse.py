"""Small idempotent SQLite warehouse for the Phase 1 ingestion slice."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from finsight_vn.contracts import FinancialRecord


SCHEMA = """
CREATE TABLE IF NOT EXISTS fct_financial_statement (
 symbol TEXT NOT NULL, fiscal_year INTEGER NOT NULL, fiscal_quarter INTEGER NOT NULL,
 metric TEXT NOT NULL, value TEXT NOT NULL, unit TEXT NOT NULL, currency TEXT NOT NULL,
 source TEXT NOT NULL, source_reference TEXT NOT NULL, ingested_at TEXT NOT NULL,
 PRIMARY KEY (symbol, fiscal_year, fiscal_quarter, metric)
);
CREATE INDEX IF NOT EXISTS idx_financial_statement_period
 ON fct_financial_statement (fiscal_year, fiscal_quarter, symbol);
CREATE INDEX IF NOT EXISTS idx_financial_statement_metric
 ON fct_financial_statement (metric, fiscal_year, fiscal_quarter);
CREATE TABLE IF NOT EXISTS data_quality_issues (
 symbol TEXT NOT NULL, period TEXT NOT NULL, dataset TEXT NOT NULL, metric TEXT NOT NULL,
 issue_type TEXT NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL,
 details TEXT NOT NULL, detected_at TEXT NOT NULL,
 PRIMARY KEY (symbol, period, dataset, metric, issue_type, source)
);
"""

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS fct_financial_statement (
 symbol TEXT NOT NULL, fiscal_year INTEGER NOT NULL,
 fiscal_quarter SMALLINT NOT NULL CHECK (fiscal_quarter BETWEEN 1 AND 4),
 metric TEXT NOT NULL, value NUMERIC NOT NULL, unit TEXT NOT NULL,
 currency TEXT NOT NULL, source TEXT NOT NULL, source_reference TEXT NOT NULL,
 ingested_at TIMESTAMPTZ NOT NULL,
 PRIMARY KEY (symbol, fiscal_year, fiscal_quarter, metric)
);
CREATE TABLE IF NOT EXISTS data_quality_issues (
 symbol TEXT NOT NULL, period TEXT NOT NULL, dataset TEXT NOT NULL,
 metric TEXT NOT NULL, issue_type TEXT NOT NULL, source TEXT NOT NULL,
 status TEXT NOT NULL, details TEXT NOT NULL, detected_at TIMESTAMPTZ NOT NULL,
 PRIMARY KEY (symbol, period, dataset, metric, issue_type, source)
);
CREATE TABLE IF NOT EXISTS fct_financial_statement_annual (
 symbol TEXT NOT NULL, fiscal_year INTEGER NOT NULL,
 statement_type TEXT NOT NULL CHECK (statement_type IN ('income_statement','balance_sheet','cash_flow')),
 metric TEXT NOT NULL, value NUMERIC NOT NULL, unit TEXT NOT NULL,
 currency TEXT NOT NULL, source TEXT NOT NULL, source_reference TEXT NOT NULL,
 ingested_at TIMESTAMPTZ NOT NULL,
 PRIMARY KEY (symbol, fiscal_year, statement_type, metric)
);
CREATE INDEX IF NOT EXISTS idx_financial_statement_annual_period
 ON fct_financial_statement_annual (fiscal_year, symbol);
"""


def load_warehouse(path: str | Path, records: Iterable[FinancialRecord], issues: Iterable[dict[str, str]]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(destination) as connection:
        connection.executescript(SCHEMA)
        connection.executemany(
            """INSERT INTO fct_financial_statement VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol,fiscal_year,fiscal_quarter,metric) DO UPDATE SET
            value=excluded.value,unit=excluded.unit,currency=excluded.currency,
            source=excluded.source,source_reference=excluded.source_reference,
            ingested_at=excluded.ingested_at""",
            [(r.symbol, r.fiscal_year, r.fiscal_quarter, r.metric, str(r.value), r.unit,
              r.currency, r.source, r.source_reference, r.ingested_at) for r in records],
        )
        connection.executemany(
            """INSERT INTO data_quality_issues VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol,period,dataset,metric,issue_type,source) DO UPDATE SET
            status=excluded.status,details=excluded.details,detected_at=excluded.detected_at""",
            [(i["symbol"], i["period"], i["dataset"], i["metric"], i["issue_type"],
              i["source"], i["status"], i["details"], i["detected_at"]) for i in issues],
        )


def save_canonical_jsonl(path: str | Path, records: Iterable[FinancialRecord]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        "".join(json.dumps(record.to_dict(), ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def load_postgres(
    dsn: str, records: Iterable[FinancialRecord], issues: Iterable[dict[str, str]]
) -> None:
    """Create the PostgreSQL schema and upsert canonical records atomically."""
    import psycopg

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(POSTGRES_SCHEMA)
            cursor.executemany(
                """INSERT INTO fct_financial_statement
                (symbol,fiscal_year,fiscal_quarter,metric,value,unit,currency,source,source_reference,ingested_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(symbol,fiscal_year,fiscal_quarter,metric) DO UPDATE SET
                value=excluded.value,unit=excluded.unit,currency=excluded.currency,
                source=excluded.source,source_reference=excluded.source_reference,
                ingested_at=excluded.ingested_at""",
                [(r.symbol, r.fiscal_year, r.fiscal_quarter, r.metric, r.value,
                  r.unit, r.currency, r.source, r.source_reference, r.ingested_at)
                 for r in records],
            )
            cursor.executemany(
                """INSERT INTO data_quality_issues
                (symbol,period,dataset,metric,issue_type,source,status,details,detected_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(symbol,period,dataset,metric,issue_type,source) DO UPDATE SET
                status=excluded.status,details=excluded.details,detected_at=excluded.detected_at""",
                [(i["symbol"], i["period"], i["dataset"], i["metric"],
                  i["issue_type"], i["source"], i["status"], i["details"],
                  i["detected_at"]) for i in issues],
            )


def annual_scopes(records: Iterable) -> dict[str, tuple[int, int]]:
    scopes: dict[str, tuple[int, int]] = {}
    for record in records:
        current = scopes.get(record.symbol)
        if current is None:
            scopes[record.symbol] = (record.fiscal_year, record.fiscal_year)
        else:
            scopes[record.symbol] = (
                min(current[0], record.fiscal_year), max(current[1], record.fiscal_year)
            )
    return scopes


def load_postgres_annual(dsn: str, records: Iterable) -> None:
    import psycopg

    records = list(records)
    if not records:
        return
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(POSTGRES_SCHEMA)
            for symbol, (start_year, end_year) in annual_scopes(records).items():
                cursor.execute(
                    """DELETE FROM fct_financial_statement_annual
                    WHERE symbol=%s AND fiscal_year BETWEEN %s AND %s""",
                    (symbol, start_year, end_year),
                )
            cursor.executemany(
                """INSERT INTO fct_financial_statement_annual
                (symbol,fiscal_year,statement_type,metric,value,unit,currency,source,source_reference,ingested_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(symbol,fiscal_year,statement_type,metric) DO UPDATE SET
                value=excluded.value,unit=excluded.unit,currency=excluded.currency,
                source=excluded.source,source_reference=excluded.source_reference,
                ingested_at=excluded.ingested_at""",
                [(r.symbol, r.fiscal_year, r.statement_type, r.metric, r.value, r.unit,
                  r.currency, r.source, r.source_reference, r.ingested_at) for r in records],
            )
