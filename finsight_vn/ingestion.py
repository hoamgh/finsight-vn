"""Provider-aware financial ingestion orchestration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from financial import build_income_statement_url, parse_income_statement_html
from finsight_vn.contracts import FinancialRecord, utc_now
from finsight_vn.normalization import normalize_rows, parse_decimal


VCI_QUARTERLY_INCOME_METRICS = {
    "isa3": "revenue",
    "isa5": "gross_profit",
    "isa11": "operating_profit",
    "isa20": "net_profit",
}
VCI_QUARTERLY_BALANCE_SHEET_METRICS = {
    "bsa2": "cash",
    "bsa53": "total_assets",
    "bsa54": "total_liabilities",
    "bsa78": "equity",
}
VCI_QUARTERLY_CASH_FLOW_METRICS = {
    "cfa18": "operating_cash_flow",
    "cfa26": "investing_cash_flow",
    "cfa34": "financing_cash_flow",
}
VCI_QUARTERLY_METRICS = {
    "income_statement": VCI_QUARTERLY_INCOME_METRICS,
    "balance_sheet": VCI_QUARTERLY_BALANCE_SHEET_METRICS,
    "cash_flow": VCI_QUARTERLY_CASH_FLOW_METRICS,
}


def rolling_windows(start: str, end: str, width: int = 4) -> list[tuple[int, int]]:
    sy, sq = int(start[:4]), int(start[-1])
    ey, eq = int(end[:4]), int(end[-1])
    start_index, end_index = sy * 4 + sq - 1, ey * 4 + eq - 1
    indexes = list(range(end_index, start_index - 1, -width))
    if indexes[-1] > start_index:
        indexes.append(start_index)
    return [(index // 4, index % 4 + 1) for index in reversed(indexes)]


def ingest_cafef(symbol: str, start: str, end: str, raw_root: str | Path, session: Any = requests):
    frames = []
    root = Path(raw_root) / "cafef" / symbol.upper()
    root.mkdir(parents=True, exist_ok=True)
    for year, quarter in rolling_windows(start, end):
        requested = f"{year}Q{quarter}"
        url = build_income_statement_url(symbol, year, quarter)
        response = session.get(url, timeout=30)
        response.raise_for_status()
        html = response.text
        html_path = root / f"{requested}.html"
        html_path.write_text(html, encoding="utf-8")
        metadata = {"symbol": symbol.upper(), "requested_period": requested, "source": "cafef",
                    "source_url": url, "acquired_at": utc_now(),
                    "sha256": hashlib.sha256(html.encode("utf-8")).hexdigest()}
        html_path.with_suffix(".metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        frame = parse_income_statement_html(html)
        frames.append(frame.melt(id_vars="metric_raw", var_name="period", value_name="value"))
    rows = pd.concat(frames, ignore_index=True).dropna(subset=["value"])
    rows = rows.drop_duplicates(["period", "metric_raw"], keep="last")
    rows = rows[(rows["period"] >= start) & (rows["period"] <= end)]
    reference = str(root.resolve())
    return normalize_rows(rows.to_dict("records"), symbol=symbol, source="cafef", source_reference=reference)


def normalize_vnstock_report(data: pd.DataFrame, symbol: str, source_reference: str):
    period_columns = [str(c) for c in data.columns if str(c).startswith(tuple(str(y) for y in range(2000, 2100)))]
    rows = []
    for row in data.to_dict("records"):
        for period in period_columns:
            if "Q" in period:
                rows.append({"period": period.split("_")[0].replace("-", ""), "metric_raw": row.get("item"),
                             "code_raw": row.get("item_id"), "value": row.get(period)})
    return normalize_rows(rows, symbol=symbol, source="vci_vnstock", source_reference=source_reference)


def normalize_vci_quarterly_records(
    rows: list[dict[str, Any]], symbol: str, source_reference: str,
    ingested_at: str | None = None, *, statement_type: str = "income_statement",
) -> list[FinancialRecord]:
    """Normalize VCI rows without detaching values from their explicit period keys."""
    try:
        metric_fields = VCI_QUARTERLY_METRICS[statement_type]
    except KeyError as error:
        raise ValueError(f"Unsupported VCI quarterly statement type: {statement_type}") from error
    timestamp = ingested_at or utc_now()
    records: dict[tuple[str, int, int, str], FinancialRecord] = {}
    for row in rows:
        try:
            year = int(row["yearReport"])
            quarter = int(row["lengthReport"])
        except (KeyError, TypeError, ValueError):
            continue
        if quarter not in {1, 2, 3, 4}:
            continue
        for field, metric in metric_fields.items():
            value = parse_decimal(row.get(field))
            if value is None:
                continue
            record = FinancialRecord(
                symbol=symbol.upper(), fiscal_year=year, fiscal_quarter=quarter,
                metric=metric, value=value, unit="VND", currency="VND",
                source="vci_vnstock", source_reference=source_reference,
                ingested_at=timestamp,
            )
            records[record.key] = record
    return sorted(records.values(), key=lambda record: record.key)


def ingest_vnstock(
    symbol: str, start: str, end: str, raw_root: str | Path, api_key: str | None = None
):
    """Fetch the latest VCI-backed Vnstock window and persist its raw response."""
    if api_key:
        from vnstock.core import setup_api_key

        setup_api_key(api_key)
    from vnstock.explorer.vci.financial import Finance

    root = Path(raw_root) / "vci_vnstock" / symbol.upper()
    root.mkdir(parents=True, exist_ok=True)
    records = []
    finance = Finance(symbol=symbol, period="quarter")
    for statement_type in VCI_QUARTERLY_METRICS:
        # Fetch long-form API rows so yearReport/lengthReport stay attached to values.
        data = finance._get_financial_report(
            statement_type, period="quarter", mode="raw", limit=1000,
            dropna=False,
        )
        destination = root / f"{statement_type}_latest.json"
        acquired_at = utc_now()
        raw_rows = data.to_dict("records")
        payload = {
            "symbol": symbol.upper(), "source": "vci_vnstock",
            "statement_type": statement_type, "period_type": "quarterly",
            "acquired_at": acquired_at, "records": raw_rows,
        }
        destination.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        records.extend(normalize_vci_quarterly_records(
            raw_rows, symbol, str(destination.resolve()), acquired_at,
            statement_type=statement_type,
        ))
    return [
        record for record in records
        if start <= f"{record.fiscal_year}Q{record.fiscal_quarter}" <= end
    ]
