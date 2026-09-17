import re
import sqlite3

import pytest

from finsight_vn.sql_agent import (
    UnsafeSqlError,
    ask,
    generate_sql,
    validate_read_only_sql,
)


def sqlite_executor(_dsn, sql):
    connection = sqlite3.connect(":memory:")
    connection.execute("ATTACH DATABASE ':memory:' AS analytics")
    connection.execute(
        """CREATE TABLE analytics.mart_regular_company_quarterly (
        symbol TEXT, period TEXT, fiscal_year INTEGER, fiscal_quarter INTEGER,
        revenue NUMERIC, net_profit NUMERIC, gross_margin NUMERIC,
        revenue_yoy_growth NUMERIC, net_profit_yoy_growth NUMERIC,
        operating_cash_flow NUMERIC)"""
    )
    rows = [
        ("FPT", "2024Q4", 2024, 4, 100, 10, 0.4, None, None, 8),
        ("FPT", "2025Q4", 2025, 4, 120, 15, 0.45, 0.2, 0.5, 11),
        ("HPG", "2025Q4", 2025, 4, 200, 20, 0.2, 0.1, 0.1, 9),
        ("MWG", "2025Q4", 2025, 4, 90, 8, 0.15, 0.3, 0.2, 7),
        ("VNM", "2025Q4", 2025, 4, 80, 7, 0.5, -0.1, -0.2, 6),
    ]
    connection.executemany("INSERT INTO analytics.mart_regular_company_quarterly VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    sqlite_sql = re.sub(r"\s+NULLS LAST", "", sql, flags=re.IGNORECASE)
    cursor = connection.execute(sqlite_sql)
    columns = tuple(item[0] for item in cursor.description)
    result = tuple(cursor.fetchall())
    connection.close()
    return columns, result


def test_revenue_question_generates_approved_relation_and_executes():
    response = ask("What was FPT revenue in 2025Q4?", "unused", sqlite_executor)
    assert response.rows == (("FPT", "2025Q4", 120),)
    assert "revenue=120" in response.answer
    assert "analytics.mart_regular_company_quarterly" in response.sql


def test_period_comparison_returns_both_periods_in_order():
    response = ask(
        "Compare FPT revenue in 2024Q4 and 2025Q4.", "unused", sqlite_executor
    )
    assert [row[1] for row in response.rows] == ["2024Q4", "2025Q4"]


def test_four_company_growth_comparison_is_data_driven():
    response = ask(
        "Compare revenue growth for FPT, HPG, MWG and VNM in 2025Q4.",
        "unused",
        sqlite_executor,
    )
    assert [row[0] for row in response.rows] == ["MWG", "FPT", "HPG", "VNM"]


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM analytics.mart_regular_company_quarterly",
        "SELECT * FROM public.fct_financial_statement",
        "SELECT * FROM analytics.mart_regular_company_quarterly; DROP TABLE x",
        "SELECT * FROM analytics.mart_regular_company_quarterly -- bypass",
    ],
)
def test_read_only_validator_blocks_unsafe_or_unapproved_sql(sql):
    with pytest.raises(UnsafeSqlError):
        validate_read_only_sql(sql)


def test_generated_sql_is_read_only():
    sql = generate_sql("What was FPT gross margin in 2025Q4?")
    validate_read_only_sql(sql)
    assert sql.startswith("SELECT")
