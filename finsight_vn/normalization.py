"""Normalize provider-specific financial rows into the FinSight contract."""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from finsight_vn.contracts import FinancialRecord, utc_now


CANONICAL_METRICS = frozenset(
    {"revenue", "gross_profit", "operating_profit", "net_profit"}
)
CODE_METRICS = {"10": "revenue", "20": "gross_profit", "30": "operating_profit", "60": "net_profit"}


def normalize_label(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text.replace("đ", "d")).strip()


def metric_from_label(label: Any, code: Any = None) -> str | None:
    code_text = str(code or "").strip()
    if code_text in CODE_METRICS:
        return CODE_METRICS[code_text]
    text = normalize_label(label)
    if "doanh thu thuan" in text:
        return "revenue"
    if "loi nhuan gop" in text or "li nhun gp" in text:
        return "gross_profit"
    if "loi nhuan thuan tu hoat dong kinh doanh" in text:
        return "operating_profit"
    if "loi nhuan sau thue thu nhap doanh nghiep" in text or "li nhun sau thu" in text:
        return "net_profit"
    return None


def parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            return None
        return number if number.is_finite() else None
    text = str(value).strip()
    if not text or text.casefold() in {"nan", "none", "-", "—"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    cleaned = re.sub(r"[^0-9,.-]", "", text.strip("()"))
    if not cleaned:
        return None
    if "." in cleaned and "," not in cleaned:
        cleaned = cleaned.replace(".", "")
    elif "," in cleaned and "." not in cleaned:
        cleaned = cleaned.replace(",", "")
    else:
        cleaned = cleaned.replace(".", "").replace(",", "")
    try:
        number = Decimal(cleaned)
    except InvalidOperation:
        return None
    return -number if negative else number


def split_quarter(period: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{4})Q([1-4])", str(period))
    if not match:
        raise ValueError(f"Invalid quarterly period: {period!r}")
    return int(match.group(1)), int(match.group(2))


def normalize_rows(
    rows: Iterable[dict[str, Any]], *, symbol: str, source: str,
    source_reference: str, period_field: str = "period",
    metric_field: str = "metric_raw", value_field: str = "value",
    code_field: str = "code_raw", unit: str = "VND", currency: str = "VND",
    ingested_at: str | None = None,
) -> list[FinancialRecord]:
    timestamp = ingested_at or utc_now()
    records: dict[tuple[str, int, int, str], FinancialRecord] = {}
    for row in rows:
        metric = metric_from_label(row.get(metric_field), row.get(code_field))
        value = parse_decimal(row.get(value_field))
        if metric is None or value is None:
            continue
        year, quarter = split_quarter(str(row[period_field]))
        record = FinancialRecord(
            symbol=symbol.upper(), fiscal_year=year, fiscal_quarter=quarter,
            metric=metric, value=value, unit=unit, currency=currency,
            source=source, source_reference=source_reference,
            ingested_at=timestamp,
        )
        records[record.key] = record
    return sorted(records.values(), key=lambda item: item.key)


def normalize_official_extraction(payload: dict[str, Any], source_reference: str) -> list[FinancialRecord]:
    period = payload["column_periods"]["current_quarter"]
    rows = [
        {"period": period, "metric_raw": row.get("metric_raw"),
         "code_raw": row.get("code_raw"), "value": row.get("current_quarter")}
        for row in payload["metrics"]
    ]
    return normalize_rows(
        rows, symbol=payload["ticker"], source=payload.get("source", "official_pdf"),
        source_reference=source_reference, ingested_at=payload.get("extracted_at"),
    )
