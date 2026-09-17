"""Extract a raw Income Statement table from an official financial PDF."""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import pandas as pd


LOGGER = logging.getLogger(__name__)

INCOME_STATEMENT_TERM_PATTERNS = {
    "doanh thu thuần": re.compile(r"\bdoanh thu th(?:u|ua)n\b"),
    "giá vốn": re.compile(r"\bgia v(?:o)?n\b"),
    "lợi nhuận gộp": re.compile(r"\bl(?:o)?i nhu(?:a)?n g(?:o)?p\b"),
    "lợi nhuận sau thuế": re.compile(
        r"\bl(?:o)?i nhu(?:a)?n sau thu(?:e)?\b"
    ),
}
MIN_INCOME_STATEMENT_MATCHES = 3
EPS_ACCOUNTING_CODES = frozenset({"70", "71"})
REPORT_PERIOD_PATTERN = re.compile(r"^(?P<year>\d{4})Q(?P<quarter>[1-4])$")


class PdfExtractionError(RuntimeError):
    """Raised when candidate tables cannot be extracted from a PDF."""


class IncomeStatementIdentificationError(PdfExtractionError):
    """Raised when no single table can be identified as an Income Statement."""


def normalize_text(value: Any) -> str:
    """Normalize text for matching without changing the extracted raw values."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = unicodedata.normalize("NFKD", str(value)).casefold()
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = text.replace("đ", "d")
    return re.sub(r"\s+", " ", text).strip()


def _table_text(table: pd.DataFrame) -> str:
    values = (normalize_text(value) for value in table.to_numpy().ravel())
    return " ".join(value for value in values if value)


def income_statement_score(table: pd.DataFrame) -> tuple[int, tuple[str, ...]]:
    """Return the number and names of Income Statement terms found in a table."""
    text = _table_text(table)
    matches = tuple(
        term
        for term, pattern in INCOME_STATEMENT_TERM_PATTERNS.items()
        if pattern.search(text)
    )
    return len(matches), matches


def identify_income_statement(
    tables: Sequence[pd.DataFrame],
    min_matches: int = MIN_INCOME_STATEMENT_MATCHES,
) -> tuple[int, pd.DataFrame]:
    """Select one Income Statement using content-based scoring.

    A tie at the best qualifying score is treated as ambiguous and fails closed.
    """
    candidates: list[tuple[int, int, tuple[str, ...], pd.DataFrame]] = []

    for index, table in enumerate(tables):
        score, matches = income_statement_score(table)
        LOGGER.info(
            "Candidate table %d: shape=%s score=%d matched_terms=%s",
            index,
            table.shape,
            score,
            list(matches),
        )
        if score >= min_matches:
            candidates.append((score, index, matches, table))

    if not candidates:
        message = (
            "No Income Statement table met the confidence threshold "
            f"({min_matches}/{len(INCOME_STATEMENT_TERM_PATTERNS)} required terms)."
        )
        LOGGER.error("Income Statement extraction failure: %s", message)
        raise IncomeStatementIdentificationError(message)

    best_score = max(candidate[0] for candidate in candidates)
    best = [candidate for candidate in candidates if candidate[0] == best_score]
    if len(best) != 1:
        indexes = [candidate[1] for candidate in best]
        message = (
            "Income Statement identification is ambiguous: "
            f"tables {indexes} share the best score {best_score}."
        )
        LOGGER.error("Income Statement extraction failure: %s", message)
        raise IncomeStatementIdentificationError(message)

    _, index, matches, table = best[0]
    LOGGER.info(
        "Selected Income Statement table %d: shape=%s matched_terms=%s",
        index,
        table.shape,
        list(matches),
    )
    return index, table.copy()


def extract_candidate_tables(pdf_path: str | Path) -> list[pd.DataFrame]:
    """Extract every table detected by Docling as a pandas DataFrame."""
    source_path = Path(pdf_path).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"PDF not found: {source_path}")

    try:
        from docling.document_converter import DocumentConverter
    except ImportError as exc:
        raise PdfExtractionError(
            "Docling is required. Install project dependencies before extraction."
        ) from exc

    try:
        conversion = DocumentConverter().convert(source_path)
        tables = [
            table.export_to_dataframe(doc=conversion.document)
            for table in conversion.document.tables
        ]
    except Exception as exc:
        LOGGER.exception("PDF table extraction failed for %s", source_path)
        raise PdfExtractionError(f"Docling failed to extract {source_path}") from exc

    LOGGER.info("Detected %d table(s) in %s", len(tables), source_path)
    if not tables:
        message = f"Docling detected no tables in {source_path}"
        LOGGER.error("PDF table extraction failed: %s", message)
        raise PdfExtractionError(message)
    return tables


def _raw_cell(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return str(value)


def derive_column_periods(report_period: str) -> dict[str, str]:
    """Derive the four Income Statement column periods from a YYYYQn period."""
    match = REPORT_PERIOD_PATTERN.fullmatch(report_period)
    if not match:
        raise ValueError(
            f"Invalid report period {report_period!r}; expected format YYYYQ1-YYYYQ4."
        )

    year = int(match.group("year"))
    quarter = int(match.group("quarter"))
    ytd_suffix = {1: "Q1", 2: "H1", 3: "9M", 4: "FY"}[quarter]
    return {
        "current_quarter": f"{year}Q{quarter}",
        "prior_year_quarter": f"{year - 1}Q{quarter}",
        "current_ytd": f"{year}{ytd_suffix}",
        "prior_year_ytd": f"{year - 1}{ytd_suffix}",
    }


def table_to_metrics(
    table: pd.DataFrame,
    *,
    unit_raw: str | None,
    eps_unit_raw: str = "VND/share",
) -> list[dict[str, Any]]:
    """Map Income Statement columns while preserving every raw cell string."""
    expected_column_count = 7
    if table.shape[1] != expected_column_count:
        raise PdfExtractionError(
            "Selected Income Statement table has "
            f"{table.shape[1]} columns; expected {expected_column_count} "
            "(metric, code, note, and four reporting values)."
        )

    metrics: list[dict[str, Any]] = []
    for row in table.itertuples(index=False, name=None):
        raw_cells = [_raw_cell(value) for value in row]
        if not normalize_text(raw_cells[0]):
            continue
        metrics.append(
            {
                "metric_raw": raw_cells[0],
                "code_raw": raw_cells[1],
                "note_raw": raw_cells[2],
                "unit_raw": (
                    eps_unit_raw
                    if normalize_text(raw_cells[1]) in EPS_ACCOUNTING_CODES
                    else unit_raw
                ),
                "current_quarter": raw_cells[3],
                "prior_year_quarter": raw_cells[4],
                "current_ytd": raw_cells[5],
                "prior_year_ytd": raw_cells[6],
            }
        )
    return metrics


def extract_income_statement(
    pdf_path: str | Path,
    *,
    ticker: str,
    report_period: str,
    unit_raw: str | None = None,
    source: str = "official_pdf",
    source_url: str | None = None,
) -> dict[str, Any]:
    """Extract one raw Income Statement representation from a local PDF."""
    source_path = Path(pdf_path).expanduser().resolve()
    column_periods = derive_column_periods(report_period)
    tables = extract_candidate_tables(source_path)
    table_index, table = identify_income_statement(tables)
    metrics = table_to_metrics(table, unit_raw=unit_raw)

    if not metrics:
        message = f"Selected table {table_index} contains no usable metric rows."
        LOGGER.error("Income Statement extraction failure: %s", message)
        raise PdfExtractionError(message)

    return {
        "ticker": ticker.upper(),
        "report_period": report_period,
        "statement_type": "income_statement",
        "source": source,
        "source_type": "pdf",
        "source_file": source_path.name,
        "source_url": source_url,
        "extraction_method": "docling",
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "column_periods": column_periods,
        "metrics": metrics,
    }


def save_extraction(result: dict[str, Any], output_path: str | Path) -> Path:
    """Save an extraction result as UTF-8 JSON."""
    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf_path", type=Path)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--report-period", required=True)
    parser.add_argument("--unit-raw")
    parser.add_argument("--source", default="official_pdf")
    parser.add_argument("--source-url")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(levelname)s %(name)s: %(message)s",
    )
    result = extract_income_statement(
        args.pdf_path,
        ticker=args.ticker,
        report_period=args.report_period,
        unit_raw=args.unit_raw,
        source=args.source,
        source_url=args.source_url,
    )
    destination = save_extraction(result, args.output)
    LOGGER.info("Saved raw Income Statement JSON to %s", destination)


if __name__ == "__main__":
    main()
