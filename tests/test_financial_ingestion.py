import json
import sqlite3
from decimal import Decimal

from finsight_vn.contracts import FinancialRecord
from finsight_vn.data_quality import balance_sheet_identity_issues, reconcile
from finsight_vn.ingestion import (
    normalize_vci_quarterly_records,
    normalize_vnstock_report,
    rolling_windows,
)
from finsight_vn.normalization import metric_from_label, normalize_official_extraction, parse_decimal
from finsight_vn.warehouse import load_warehouse


def record(value, source="cafef"):
    return FinancialRecord("FPT", 2024, 2, "revenue", Decimal(value), "VND", "VND", source, source, "now")


def test_rolling_windows_cover_requested_history():
    assert rolling_windows("2023Q1", "2026Q2") == [(2023, 1), (2023, 2), (2024, 2), (2025, 2), (2026, 2)]


def test_metric_mapping_and_accounting_number_parsing():
    assert metric_from_label("3. Doanh thu thuần về bán hàng") == "revenue"
    assert metric_from_label("OCR damage", "60") == "net_profit"
    assert parse_decimal("(1.234.567)") == Decimal("-1234567")
    assert parse_decimal(4278629180000.0) == Decimal("4278629180000.0")
    assert parse_decimal(0) == Decimal("0")


def test_official_fills_missing_and_resolves_conflict():
    selected, issues = reconcile([record("100")], [record("120", "vci")], official=[record("110", "official_fpt")])
    assert selected[0].value == Decimal("110")
    assert issues[0]["status"] == "RESOLVED_OFFICIAL"


def test_incremental_source_wins_open_conflict_without_official_report():
    selected, issues = reconcile(
        [record("100")], [record("120", "vci")], prefer_secondary=True
    )
    assert selected[0].source == "vci"
    assert selected[0].value == Decimal("120")
    assert issues[0]["status"] == "OPEN"


def test_preferred_source_wins_even_within_tolerance_to_avoid_mixed_statements():
    selected, issues = reconcile(
        [record("100")], [record("100.1", "vci")], prefer_secondary=True
    )
    assert selected[0].source == "vci"
    assert selected[0].value == Decimal("100.1")
    assert issues == []


def test_official_extraction_uses_current_quarter_only():
    payload = {"ticker": "FPT", "source": "official_fpt", "extracted_at": "now",
               "column_periods": {"current_quarter": "2024Q2"},
               "metrics": [{"metric_raw": "x", "code_raw": "10", "current_quarter": "1.000"}]}
    result = normalize_official_extraction(payload, "report.pdf")
    assert result[0].key == ("FPT", 2024, 2, "revenue")
    assert result[0].value == Decimal("1000")


def test_vnstock_report_normalization_handles_report_orientation():
    import pandas as pd

    data = pd.DataFrame([{"item": "Doanh thu thuần", "item_id": "10", "2026-Q2": "2.000"}])
    result = normalize_vnstock_report(data, "FPT", "raw.json")
    assert result[0].key == ("FPT", 2026, 2, "revenue")


def test_vci_fpt_2025q3_uses_explicit_upstream_period():
    rows = [{"yearReport": 2025, "lengthReport": 3, "isa3": 17204521225302}]

    result = normalize_vci_quarterly_records(rows, "FPT", "raw.json")

    assert result[0].key == ("FPT", 2025, 3, "revenue")
    assert result[0].value == Decimal("17204521225302")
    assert result[0].source_reference == "raw.json"


def test_vci_hpg_2025q3_uses_explicit_upstream_period():
    rows = [{"yearReport": 2025, "lengthReport": 3, "isa3": 36407416403924}]

    result = normalize_vci_quarterly_records(rows, "HPG", "raw.json")

    assert result[0].key == ("HPG", 2025, 3, "revenue")
    assert result[0].value == Decimal("36407416403924")


def test_vci_four_period_values_cannot_detach_from_explicit_periods():
    rows = [
        {"yearReport": 2026, "lengthReport": 2, "isa3": 4},
        {"yearReport": 2025, "lengthReport": 3, "isa3": 1},
        {"yearReport": 2026, "lengthReport": 1, "isa3": 3},
        {"yearReport": 2025, "lengthReport": 4, "isa3": 2},
    ]

    result = normalize_vci_quarterly_records(rows, "FPT", "raw.json")

    assert {record.key: record.value for record in result} == {
        ("FPT", 2025, 3, "revenue"): Decimal("1"),
        ("FPT", 2025, 4, "revenue"): Decimal("2"),
        ("FPT", 2026, 1, "revenue"): Decimal("3"),
        ("FPT", 2026, 2, "revenue"): Decimal("4"),
    }


def test_vci_balance_sheet_fields_and_provenance_are_preserved():
    rows = [{
        "yearReport": 2025, "lengthReport": 4,
        "bsa2": 10522105729992, "bsa53": 88141991634625,
        "bsa54": 44393950887086, "bsa78": 43748040747539,
    }]

    result = normalize_vci_quarterly_records(
        rows, "FPT", "balance-sheet.json", "observed-at",
        statement_type="balance_sheet",
    )

    assert {record.metric: record.value for record in result} == {
        "cash": Decimal("10522105729992"),
        "total_assets": Decimal("88141991634625"),
        "total_liabilities": Decimal("44393950887086"),
        "equity": Decimal("43748040747539"),
    }
    assert {record.key[:3] for record in result} == {("FPT", 2025, 4)}
    assert {record.source_reference for record in result} == {"balance-sheet.json"}
    assert {record.ingested_at for record in result} == {"observed-at"}


def test_vci_cash_flow_fields_are_standalone_quarter_values():
    rows = [{
        "yearReport": 2025, "lengthReport": 3,
        "cfa18": 8294398995676, "cfa26": -13938241340574,
        "cfa34": 4047042703711,
    }]

    result = normalize_vci_quarterly_records(
        rows, "HPG", "cash-flow.json", statement_type="cash_flow"
    )

    assert {record.metric: record.value for record in result} == {
        "operating_cash_flow": Decimal("8294398995676"),
        "investing_cash_flow": Decimal("-13938241340574"),
        "financing_cash_flow": Decimal("4047042703711"),
    }
    assert {record.key[:3] for record in result} == {("HPG", 2025, 3)}


def test_vci_shuffled_statement_rows_retain_period_value_associations():
    rows = [
        {"yearReport": 2026, "lengthReport": 2, "bsa53": 4},
        {"yearReport": 2025, "lengthReport": 3, "bsa53": 1},
        {"yearReport": 2026, "lengthReport": 1, "bsa53": 3},
        {"yearReport": 2025, "lengthReport": 4, "bsa53": 2},
    ]

    result = normalize_vci_quarterly_records(
        rows, "FPT", "balance-sheet.json", statement_type="balance_sheet"
    )

    assert {(r.fiscal_year, r.fiscal_quarter): r.value for r in result} == {
        (2025, 3): Decimal("1"), (2025, 4): Decimal("2"),
        (2026, 1): Decimal("3"), (2026, 2): Decimal("4"),
    }


def test_vci_annual_length_report_is_excluded_from_quarterly_normalization():
    rows = [
        {"yearReport": 2025, "lengthReport": 4, "cfa18": 10},
        {"yearReport": 2025, "lengthReport": 5, "cfa18": 99},
    ]

    result = normalize_vci_quarterly_records(
        rows, "FPT", "cash-flow.json", statement_type="cash_flow"
    )

    assert [(record.fiscal_quarter, record.value) for record in result] == [
        (4, Decimal("10"))
    ]


def test_balance_sheet_identity_validation_honors_explicit_tolerance():
    def balance(metric, value):
        return FinancialRecord(
            "FPT", 2025, 4, metric, Decimal(value), "VND", "VND",
            "vci_vnstock", "balance-sheet.json", "now",
        )

    valid = [balance("total_assets", "100"),
             balance("total_liabilities", "60"), balance("equity", "39.5")]
    invalid = [balance("total_assets", "102"), *valid[1:]]

    assert balance_sheet_identity_issues(valid, tolerance=Decimal("0.5")) == []
    issues = balance_sheet_identity_issues(invalid, tolerance=Decimal("0.5"))
    assert len(issues) == 1
    assert issues[0]["issue_type"] == "BALANCE_SHEET_IDENTITY"
    assert "difference=2.5" in issues[0]["details"]


def test_warehouse_upsert_is_idempotent(tmp_path):
    path = tmp_path / "warehouse.db"
    load_warehouse(path, [record("100")], [])
    load_warehouse(path, [record("101")], [])
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM fct_financial_statement").fetchone()[0] == 1
        assert connection.execute("SELECT value FROM fct_financial_statement").fetchone()[0] == "101"
