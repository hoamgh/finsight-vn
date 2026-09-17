"""CafeF annual financial-statement ingestion (quarter=0 only)."""

from __future__ import annotations

import hashlib
import json
import re
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from finsight_vn.contracts import AnnualFinancialRecord, utc_now
from finsight_vn.normalization import metric_from_label, normalize_label, parse_decimal


CAFEF_ANNUAL_URL = "https://cafef.vn/du-lieu/BaoCaoTaiChinh_V2.aspx"
STATEMENT_TYPES = {
    "income_statement": "IncSta",
    "balance_sheet": "BSheet",
    "cash_flow": "CashFlow",
}
STATEMENT_SLUGS = {
    "income_statement": ("incsta", "ket-qua-hoat-dong-kinh-doanh"),
    "balance_sheet": ("bsheet", "can-doi-ke-toan"),
    "cash_flow": ("cashflow", "luu-chuyen-tien-te"),
}
VCI_CASH_FLOW_METRICS = {
    "operating_cash_flow": "operating_cash_flow",
    "investing_cash_flow": "investing_cash_flow",
    "financing_cash_flow": "financing_cash_flow",
}


def cafef_annual_url(symbol: str, statement_type: str, year: int) -> str:
    provider_path, slug = STATEMENT_SLUGS[statement_type]
    ticker = symbol.lower()
    return (
        f"https://cafef.vn/du-lieu/bao-cao-tai-chinh/{ticker}/"
        f"{provider_path}/{year}/0/0/0/{slug}-cong-ty-co-phan-{ticker}.chn"
    )


def annual_metric(label: Any, statement_type: str) -> str | None:
    text = normalize_label(label)
    if statement_type == "income_statement":
        metric = metric_from_label(label)
        if metric:
            return metric
        if text == "i. thu nhap lai thuan":
            return "net_interest_income"
        if text in {"xiii. loi nhuan sau thue", "loi nhuan sau thue"}:
            return "net_profit"
        return None
    if statement_type == "balance_sheet":
        exact = {
            "i. tien va cac khoan tuong duong tien": "cash",
            "tong cong tai san": "total_assets",
            "c. no phai tra": "total_liabilities",
            "d.von chu so huu": "equity",
            "d. von chu so huu": "equity",
            "tong tai san co": "total_assets",
            "tong no phai tra": "total_liabilities",
            "viii.von chu so huu": "equity",
            "viii. von chu so huu": "equity",
        }
        return exact.get(text)
    if statement_type == "cash_flow":
        if text in {
            "luu chuyen tien thuan tu hoat dong kinh doanh",
            "i. luu chuyen tien thuan tu hoat dong kinh doanh",
        }:
            return "operating_cash_flow"
        if text == "luu chuyen tien thuan tu hoat dong dau tu":
            return "investing_cash_flow"
        if text == "luu chuyen tien thuan tu hoat dong tai chinh":
            return "financing_cash_flow"
    return None


def parse_annual_html(
    html: str, *, symbol: str, statement_type: str, source_reference: str,
    ingested_at: str | None = None,
) -> list[AnnualFinancialRecord]:
    tables = pd.read_html(StringIO(html))
    header = next(
        (table for table in tables if len(re.findall(r"\b20\d{2}\b", " ".join(map(str, table.to_numpy().ravel())))) >= 4),
        None,
    )
    if header is None:
        raise ValueError("CafeF annual year columns not found")
    header_text = " ".join(map(str, header.to_numpy().ravel()))
    if re.search(r"Quý\s*[1-4]", header_text, re.IGNORECASE):
        raise ValueError("Quarterly CafeF response rejected by annual parser")
    years = re.findall(r"\b(20\d{2})\b", header_text)
    years = list(dict.fromkeys(years))
    if len(years) != 4:
        raise ValueError(f"Expected four annual columns, found {years}")

    candidates = [
        table for table in tables
        if table is not header and table.shape[1] >= len(years) + 1
    ]
    if not candidates:
        raise ValueError("CafeF annual data table not found")
    data = max(candidates, key=lambda table: table.shape[0])
    data = data.iloc[:, :5].copy()
    data.columns = ["metric_raw", *years]
    timestamp = ingested_at or utc_now()
    records: dict[tuple[str, int, str, str], AnnualFinancialRecord] = {}
    for row in data.to_dict("records"):
        metric = annual_metric(row["metric_raw"], statement_type)
        if metric is None:
            continue
        for year in years:
            value = parse_decimal(row.get(year))
            if value is None:
                continue
            record = AnnualFinancialRecord(
                symbol=symbol.upper(), fiscal_year=int(year), statement_type=statement_type,
                metric=metric, value=value, unit="VND", currency="VND", source="cafef",
                source_reference=source_reference, ingested_at=timestamp,
            )
            records[record.key] = record
    return sorted(records.values(), key=lambda record: record.key)


def ingest_cafef_annual(
    symbol: str, start_year: int, end_year: int, raw_root: str | Path,
    session: Any = requests,
) -> list[AnnualFinancialRecord]:
    root = Path(raw_root) / "cafef" / symbol.upper() / "annual"
    root.mkdir(parents=True, exist_ok=True)
    records: list[AnnualFinancialRecord] = []
    for requested_year in annual_windows(start_year, end_year):
        for statement_type, provider_type in STATEMENT_TYPES.items():
            response = session.get(
                CAFEF_ANNUAL_URL,
                params={
                    "quarter": 0, "symbol": symbol.upper(),
                    "type": provider_type, "year": requested_year,
                },
                timeout=30,
            )
            if response.status_code == 404:
                response = session.get(
                    cafef_annual_url(symbol, statement_type, requested_year), timeout=30
                )
            response.raise_for_status()
            html = response.text
            path = root / f"{requested_year}_{statement_type}.html"
            path.write_text(html, encoding="utf-8")
            metadata = {
                "symbol": symbol.upper(), "period_type": "annual", "quarter": 0,
                "requested_year": requested_year, "statement_type": statement_type,
                "source": "cafef", "source_url": response.url, "acquired_at": utc_now(),
                "sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
            }
            metadata_path = path.with_suffix(".metadata.json")
            metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            records.extend(
                parse_annual_html(
                    html, symbol=symbol, statement_type=statement_type,
                    source_reference=str(metadata_path.resolve()), ingested_at=metadata["acquired_at"],
                )
            )
    selected = {
        record.key: record for record in records
        if start_year <= record.fiscal_year <= end_year
    }
    return sorted(selected.values(), key=lambda record: record.key)


def annual_windows(start_year: int, end_year: int, width: int = 4) -> list[int]:
    if start_year > end_year:
        raise ValueError("start_year must not be after end_year")
    endpoints = []
    endpoint = end_year
    while endpoint >= start_year:
        endpoints.append(endpoint)
        if endpoint - width + 1 <= start_year:
            break
        endpoint -= width
    return sorted(endpoints)


def ingest_vnstock_annual_cash_flow(
    symbol: str, start_year: int, end_year: int, raw_root: str | Path,
    api_key: str | None = None,
) -> list[AnnualFinancialRecord]:
    """Fetch VCI annual cash flow as a structured fallback for CafeF nulls."""
    if api_key:
        from vnstock.core import setup_api_key

        setup_api_key(api_key)
    from vnstock import Fundamental

    data = Fundamental().equity(symbol).cash_flow(period="year")
    if data.empty:
        return []
    root = Path(raw_root) / "vci_vnstock" / symbol.upper() / "annual"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "cash_flow_latest.json"
    acquired_at = utc_now()
    path.write_text(
        json.dumps(
            {"symbol": symbol.upper(), "period_type": "annual",
             "statement_type": "cash_flow", "source": "vci_vnstock",
             "acquired_at": acquired_at, "records": data.to_dict("records")},
            ensure_ascii=False, indent=2, default=str,
        ),
        encoding="utf-8",
    )
    records = []
    for row in data.to_dict("records"):
        metric = VCI_CASH_FLOW_METRICS.get(str(row.get("item_id")))
        if metric is None:
            continue
        for column, raw_value in row.items():
            if not re.fullmatch(r"20\d{2}", str(column)):
                continue
            year = int(column)
            value = parse_decimal(raw_value)
            if value is None or not start_year <= year <= end_year:
                continue
            records.append(
                AnnualFinancialRecord(
                    symbol=symbol.upper(), fiscal_year=year,
                    statement_type="cash_flow", metric=metric, value=value,
                    unit="VND", currency="VND", source="vci_vnstock",
                    source_reference=str(path.resolve()), ingested_at=acquired_at,
                )
            )
    return sorted(records, key=lambda record: record.key)
