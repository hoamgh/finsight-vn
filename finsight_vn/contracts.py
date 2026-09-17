"""Canonical FinSight data contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class FinancialRecord:
    symbol: str
    fiscal_year: int
    fiscal_quarter: int
    metric: str
    value: Decimal
    unit: str
    currency: str
    source: str
    source_reference: str
    ingested_at: str

    @property
    def key(self) -> tuple[str, int, int, str]:
        return (self.symbol, self.fiscal_year, self.fiscal_quarter, self.metric)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["value"] = str(self.value)
        return result


@dataclass(frozen=True)
class AnnualFinancialRecord:
    symbol: str
    fiscal_year: int
    statement_type: str
    metric: str
    value: Decimal
    unit: str
    currency: str
    source: str
    source_reference: str
    ingested_at: str

    @property
    def key(self) -> tuple[str, int, str, str]:
        return (self.symbol, self.fiscal_year, self.statement_type, self.metric)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["value"] = str(self.value)
        result["period_type"] = "annual"
        return result


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
