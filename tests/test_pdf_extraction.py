import pandas as pd
import pytest

from finsight_vn.pdf_extraction import (
    IncomeStatementIdentificationError,
    PdfExtractionError,
    derive_column_periods,
    extract_income_statement,
    identify_income_statement,
    normalize_text,
    table_to_metrics,
)


def test_normalize_text_handles_case_and_repeated_whitespace():
    assert normalize_text("  DOANH THU\n\tTHUẦN  ") == "doanh thu thuan"


def test_identifies_terms_with_common_missing_diacritic_ocr_output():
    ocr_table = pd.DataFrame(
        [
            ["Doanh thu thun", "100"],
            ["Giá vn hàng bán", "60"],
            ["Li nhun gp", "40"],
            ["Li nhun sau thu", "25"],
        ]
    )

    index, selected = identify_income_statement([ocr_table])

    assert index == 0
    pd.testing.assert_frame_equal(selected, ocr_table)


def test_identifies_income_statement_by_content():
    balance_sheet = pd.DataFrame(
        [["Tài sản ngắn hạn", "100"], ["Nợ phải trả", "40"]]
    )
    income_statement = pd.DataFrame(
        [
            ["Doanh thu thuần", "100"],
            ["Giá vốn hàng bán", "60"],
            ["Lợi nhuận gộp", "40"],
            ["Lợi nhuận sau thuế", "25"],
        ]
    )

    index, selected = identify_income_statement(
        [balance_sheet, income_statement]
    )

    assert index == 1
    pd.testing.assert_frame_equal(selected, income_statement)


def test_rejects_table_below_confidence_threshold():
    incomplete = pd.DataFrame(
        [["Doanh thu thuần", "100"], ["Giá vốn hàng bán", "60"]]
    )

    with pytest.raises(
        IncomeStatementIdentificationError,
        match="confidence threshold",
    ):
        identify_income_statement([incomplete])


def test_rejects_ambiguous_best_candidates():
    candidate = pd.DataFrame(
        [
            ["Doanh thu thuần", "100"],
            ["Giá vốn", "60"],
            ["Lợi nhuận gộp", "40"],
        ]
    )

    with pytest.raises(
        IncomeStatementIdentificationError,
        match="ambiguous",
    ):
        identify_income_statement([candidate, candidate.copy()])


def test_maps_raw_income_statement_columns_explicitly():
    table = pd.DataFrame(
        [[" Doanh thu thuần ", "10", "25", "100", "90", "190", "170"]]
    )

    assert table_to_metrics(table, unit_raw="VND") == [
        {
            "metric_raw": " Doanh thu thuần ",
            "code_raw": "10",
            "note_raw": "25",
            "unit_raw": "VND",
            "current_quarter": "100",
            "prior_year_quarter": "90",
            "current_ytd": "190",
            "prior_year_ytd": "170",
        }
    ]


def test_rejects_unexpected_income_statement_column_count():
    with pytest.raises(PdfExtractionError, match="expected 7"):
        table_to_metrics(
            pd.DataFrame([["Doanh thu thuần", "100"]]), unit_raw="VND"
        )


def test_derives_column_periods_from_report_period():
    assert derive_column_periods("2024Q2") == {
        "current_quarter": "2024Q2",
        "prior_year_quarter": "2023Q2",
        "current_ytd": "2024H1",
        "prior_year_ytd": "2023H1",
    }


def test_rejects_invalid_report_period():
    with pytest.raises(ValueError, match="expected format"):
        derive_column_periods("2024H1")


def test_bronze_schema_preserves_raw_values_and_provenance(monkeypatch, tmp_path):
    table = pd.DataFrame(
        [
            [
                "Doanh thu thuần",
                "10",
                "25",
                "15.245.226.416.020",
                "12.484.364.264.902",
                "29.338.154.829.719",
                "24.165.743.148.205",
            ],
            [
                "Lợi nhuận gộp",
                "20",
                "",
                "(65.748.307.687)",
                "40",
                "80",
                "70",
            ],
            ["Lợi nhuận sau thuế", "60", "", "30", "20", "50", "40"],
            ["Lãi cơ bản trên cổ phiếu", "70", "", "1.000", "900", "1.900", "1.700"],
        ]
    )
    pdf_path = tmp_path / "statement.pdf"
    pdf_path.touch()
    monkeypatch.setattr(
        "finsight_vn.pdf_extraction.extract_candidate_tables", lambda _: [table]
    )

    result = extract_income_statement(
        pdf_path,
        ticker="FPT",
        report_period="2024Q2",
        unit_raw="VND",
        source="official_fpt",
    )

    assert "period" not in result
    assert result["report_period"] == "2024Q2"
    assert result["source_type"] == "pdf"
    assert result["source_url"] is None
    assert result["extraction_method"] == "docling"
    assert result["extracted_at"].endswith("+00:00")
    assert result["metrics"][0]["code_raw"] == "10"
    assert result["metrics"][0]["note_raw"] == "25"
    assert result["metrics"][0]["current_quarter"] == "15.245.226.416.020"
    assert result["metrics"][1]["current_quarter"] == "(65.748.307.687)"
    assert result["metrics"][1]["unit_raw"] == "VND"
    assert result["metrics"][3]["unit_raw"] == "VND/share"
