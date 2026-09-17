from decimal import Decimal

import pandas as pd

from finsight_vn.quarterly_ingestion import cafef_quarterly_url, parse_quarterly_html


def html_table(frame):
    return frame.to_html(index=False, header=False)


def test_quarterly_url_cannot_silently_become_annual():
    url = cafef_quarterly_url("FPT", "cash_flow", 2016, 1)
    assert "/2016/1/0/0/" in url
    assert "/cashflow/" in url


def test_quarterly_parser_maps_statement_metrics_and_periods():
    header = pd.DataFrame([[
        "Trước", "Sau", "Quý 2- 2015", "Quý 3- 2015",
        "Quý 4- 2015", "Quý 1- 2016",
    ]])
    data = pd.DataFrame([
        ["TỔNG CỘNG TÀI SẢN", "1.000.000.000", "2.000.000.000",
         "3.000.000.000", "4.000.000.000", None],
    ])
    result = parse_quarterly_html(
        html_table(header) + html_table(data), symbol="FPT",
        statement_type="balance_sheet", source_reference="raw.html",
    )
    assert result[-1].key == ("FPT", 2016, 1, "total_assets")
    assert result[-1].value == Decimal("4000000000")
