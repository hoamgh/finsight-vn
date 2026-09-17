from decimal import Decimal

import pandas as pd

from finsight_vn.annual_ingestion import (
    VCI_CASH_FLOW_METRICS, annual_metric, annual_windows, cafef_annual_url,
    parse_annual_html,
)
from finsight_vn.contracts import AnnualFinancialRecord
from finsight_vn.warehouse import annual_scopes


def html_table(frame):
    return frame.to_html(index=False, header=False)


def test_annual_metric_mapping_is_statement_specific():
    assert annual_metric("TỔNG CỘNG TÀI SẢN", "balance_sheet") == "total_assets"
    assert annual_metric("D.VỐN CHỦ SỞ HỮU", "balance_sheet") == "equity"
    assert annual_metric("Lưu chuyển tiền thuần từ hoạt động kinh doanh", "cash_flow") == "operating_cash_flow"


def test_annual_windows_cover_long_history_without_one_off_requests():
    assert annual_windows(2016, 2025) == [2017, 2021, 2025]
    assert annual_windows(2023, 2025) == [2025]


def test_annual_url_is_explicitly_annual():
    url = cafef_annual_url("FPT", "income_statement", 2017)
    assert "/2017/0/0/0/" in url
    assert "/incsta/" in url


def test_v2_then_historical_route_strategy_keeps_bank_schema_available():
    # The V2 endpoint exposes bank-specific statements; the pretty historical
    # route is retained as a fallback for old non-bank windows that return 404.
    from finsight_vn.annual_ingestion import CAFEF_ANNUAL_URL

    assert CAFEF_ANNUAL_URL.endswith("BaoCaoTaiChinh_V2.aspx")


def test_bank_specific_annual_metrics_are_not_dropped():
    assert annual_metric("I. Thu nhập lãi thuần", "income_statement") == "net_interest_income"
    assert annual_metric("TỔNG TÀI SẢN CÓ", "balance_sheet") == "total_assets"
    assert annual_metric("TỔNG NỢ PHẢI TRẢ", "balance_sheet") == "total_liabilities"


def test_annual_scopes_limit_stale_cleanup_to_loaded_company_years():
    def row(symbol, year):
        return AnnualFinancialRecord(
            symbol, year, "income_statement", "revenue", Decimal("1"),
            "VND", "VND", "cafef", "raw", "now",
        )

    assert annual_scopes([row("FPT", 2016), row("FPT", 2025), row("VCB", 2020)]) == {
        "FPT": (2016, 2025), "VCB": (2020, 2020)
    }


def test_vci_cash_flow_semantic_ids_are_canonical():
    expected = {"operating_cash_flow", "investing_cash_flow", "financing_cash_flow"}
    assert set(VCI_CASH_FLOW_METRICS) == expected


def test_annual_parser_accepts_years_and_rejects_quarters():
    header = pd.DataFrame([["Trước", "Sau", "2022", "2023", "2024", "2025"]])
    data = pd.DataFrame([[
        "TỔNG CỘNG TÀI SẢN", "1.000.000.000", "2.000.000.000",
        "3.000.000.000", "4.000.000.000", None,
    ]])
    result = parse_annual_html(
        html_table(header) + html_table(data), symbol="FPT", statement_type="balance_sheet",
        source_reference="raw.html",
    )
    assert [record.fiscal_year for record in result] == [2022, 2023, 2024, 2025]
    assert result[-1].value == Decimal("4000000000")

    bad_header = pd.DataFrame([["Quý 1-2025", "Quý 2-2025", "2023", "2024", "2025", "2026"]])
    try:
        parse_annual_html(
            html_table(bad_header) + html_table(data), symbol="FPT",
            statement_type="balance_sheet", source_reference="raw.html",
        )
    except ValueError as error:
        assert "Quarterly" in str(error)
    else:
        raise AssertionError("Quarterly response was accepted as annual")
