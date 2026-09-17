"""Multi-statement CafeF quarterly historical ingestion."""

from __future__ import annotations

import hashlib
import json
import re
import time
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from finsight_vn.annual_ingestion import STATEMENT_SLUGS, annual_metric
from finsight_vn.contracts import FinancialRecord, utc_now
from finsight_vn.ingestion import rolling_windows
from finsight_vn.normalization import parse_decimal, split_quarter


def cafef_quarterly_url(symbol: str, statement_type: str, year: int, quarter: int) -> str:
    provider_path, slug = STATEMENT_SLUGS[statement_type]
    ticker = symbol.lower()
    return (
        f"https://cafef.vn/du-lieu/bao-cao-tai-chinh/{ticker}/"
        f"{provider_path}/{year}/{quarter}/0/0/{slug}-cong-ty-co-phan-{ticker}.chn"
    )


def parse_quarterly_html(
    html: str, *, symbol: str, statement_type: str, source_reference: str,
    ingested_at: str | None = None,
) -> list[FinancialRecord]:
    tables = pd.read_html(StringIO(html))
    header = None
    periods = []
    for table in tables:
        text = " ".join(map(str, table.to_numpy().ravel()))
        matches = re.findall(r"Quý\s*([1-4])\s*-?\s*(\d{4})", text, re.IGNORECASE)
        if len(matches) == 4:
            header = table
            periods = [f"{year}Q{quarter}" for quarter, year in matches]
            break
    if header is None:
        raise ValueError("CafeF quarterly columns not found")
    candidates = [
        table for table in tables
        if table is not header and table.shape[1] >= len(periods) + 1
    ]
    if not candidates:
        raise ValueError("CafeF quarterly data table not found")
    data = max(candidates, key=lambda table: table.shape[0]).iloc[:, :5].copy()
    data.columns = ["metric_raw", *periods]
    timestamp = ingested_at or utc_now()
    records: dict[tuple[str, int, int, str], FinancialRecord] = {}
    for row in data.to_dict("records"):
        metric = annual_metric(row["metric_raw"], statement_type)
        if metric is None:
            continue
        for period in periods:
            value = parse_decimal(row.get(period))
            if value is None:
                continue
            year, quarter = split_quarter(period)
            record = FinancialRecord(
                symbol=symbol.upper(), fiscal_year=year, fiscal_quarter=quarter,
                metric=metric, value=value, unit="VND", currency="VND",
                source="cafef", source_reference=source_reference,
                ingested_at=timestamp,
            )
            records[record.key] = record
    return sorted(records.values(), key=lambda record: record.key)


def _get_with_retry(session: Any, url: str, attempts: int = 3):
    for attempt in range(attempts):
        response = session.get(url, timeout=30)
        if response.status_code not in {429, 500, 502, 503, 504}:
            response.raise_for_status()
            return response
        if attempt + 1 < attempts:
            time.sleep(2 ** attempt)
    response.raise_for_status()


def ingest_cafef_quarterly(
    symbol: str, start: str, end: str, raw_root: str | Path,
    session: Any = requests,
) -> list[FinancialRecord]:
    root = Path(raw_root) / "cafef" / symbol.upper() / "quarterly"
    root.mkdir(parents=True, exist_ok=True)
    records = []
    for year, quarter in rolling_windows(start, end):
        requested_period = f"{year}Q{quarter}"
        for statement_type in STATEMENT_SLUGS:
            url = cafef_quarterly_url(symbol, statement_type, year, quarter)
            response = _get_with_retry(session, url)
            html = response.text
            path = root / f"{requested_period}_{statement_type}.html"
            path.write_text(html, encoding="utf-8")
            metadata = {
                "symbol": symbol.upper(), "period_type": "quarterly",
                "requested_period": requested_period, "statement_type": statement_type,
                "source": "cafef", "source_url": response.url, "acquired_at": utc_now(),
                "sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
            }
            metadata_path = path.with_suffix(".metadata.json")
            metadata_path.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            records.extend(
                parse_quarterly_html(
                    html, symbol=symbol, statement_type=statement_type,
                    source_reference=str(metadata_path.resolve()),
                    ingested_at=metadata["acquired_at"],
                )
            )
    selected = {
        record.key: record for record in records
        if start <= f"{record.fiscal_year}Q{record.fiscal_quarter}" <= end
    }
    return sorted(selected.values(), key=lambda record: record.key)
