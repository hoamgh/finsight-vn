"""Completeness and cross-source reconciliation for financial records."""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from finsight_vn.contracts import FinancialRecord, utc_now


def quarter_range(start: str, end: str) -> list[str]:
    sy, sq = int(start[:4]), int(start[-1])
    ey, eq = int(end[:4]), int(end[-1])
    result = []
    while (sy, sq) <= (ey, eq):
        result.append(f"{sy}Q{sq}")
        sy, sq = (sy + 1, 1) if sq == 4 else (sy, sq + 1)
    return result


def reconcile(
    primary: Iterable[FinancialRecord], secondary: Iterable[FinancialRecord],
    *, tolerance: Decimal = Decimal("0.005"), official: Iterable[FinancialRecord] = (),
    prefer_secondary: bool = False,
) -> tuple[list[FinancialRecord], list[dict[str, str]]]:
    chosen = {record.key: record for record in primary}
    issues: list[dict[str, str]] = []
    official_map = {record.key: record for record in official}
    for candidate in secondary:
        current = chosen.get(candidate.key)
        if current is None:
            chosen[candidate.key] = candidate
            continue
        denominator = max(abs(current.value), abs(candidate.value), Decimal("1"))
        is_conflict = abs(current.value - candidate.value) / denominator > tolerance
        if is_conflict:
            resolution = official_map.get(candidate.key)
            if resolution is not None:
                chosen[candidate.key] = resolution
            elif prefer_secondary:
                chosen[candidate.key] = candidate
            issues.append({
                "symbol": candidate.symbol,
                "period": f"{candidate.fiscal_year}Q{candidate.fiscal_quarter}",
                "dataset": "financial_statement", "metric": candidate.metric,
                "issue_type": "SOURCE_CONFLICT", "source": f"{current.source},{candidate.source}",
                "status": "RESOLVED_OFFICIAL" if resolution else "OPEN",
                "details": f"{current.value} vs {candidate.value}", "detected_at": utc_now(),
            })
        elif prefer_secondary:
            # Select one coherent provider for the whole statement. Keeping a
            # near-equal primary value here can mix CafeF assets with VCI
            # liabilities/equity and manufacture an accounting-identity error.
            chosen[candidate.key] = candidate
    for key, resolution in official_map.items():
        if key not in chosen:
            chosen[key] = resolution
            issues.append({
                "symbol": resolution.symbol,
                "period": f"{resolution.fiscal_year}Q{resolution.fiscal_quarter}",
                "dataset": "financial_statement", "metric": resolution.metric,
                "issue_type": "MISSING_PERIOD_FALLBACK", "source": resolution.source,
                "status": "RESOLVED_OFFICIAL", "details": "Filled from official report",
                "detected_at": utc_now(),
            })
    return sorted(chosen.values(), key=lambda item: item.key), issues


def completeness_issues(records: Iterable[FinancialRecord], start: str, end: str, source: str) -> list[dict[str, str]]:
    records = list(records)
    symbol = records[0].symbol if records else "UNKNOWN"
    actual = {f"{r.fiscal_year}Q{r.fiscal_quarter}" for r in records}
    return [
        {"symbol": symbol, "period": period, "dataset": "financial_statement",
         "metric": "*", "issue_type": "MISSING_PERIOD", "source": source,
         "status": "OPEN", "details": "No canonical metrics for expected quarter",
         "detected_at": utc_now()}
        for period in quarter_range(start, end) if period not in actual
    ]


def balance_sheet_identity_issues(
    records: Iterable[FinancialRecord], *, tolerance: Decimal = Decimal("1"),
) -> list[dict[str, str]]:
    """Report balance-sheet identity violations without changing source values."""
    required = {"total_assets", "total_liabilities", "equity"}
    grouped: dict[tuple[str, int, int], dict[str, FinancialRecord]] = {}
    for record in records:
        if record.metric in required:
            grouped.setdefault(
                (record.symbol, record.fiscal_year, record.fiscal_quarter), {}
            )[record.metric] = record

    issues = []
    for (symbol, year, quarter), values in sorted(grouped.items()):
        if not required <= values.keys():
            continue
        assets = values["total_assets"].value
        liabilities = values["total_liabilities"].value
        equity = values["equity"].value
        difference = assets - liabilities - equity
        if abs(difference) <= tolerance:
            continue
        sources = sorted({record.source for record in values.values()})
        issues.append({
            "symbol": symbol, "period": f"{year}Q{quarter}",
            "dataset": "financial_statement", "metric": "total_assets",
            "issue_type": "BALANCE_SHEET_IDENTITY", "source": ",".join(sources),
            "status": "OPEN",
            "details": (
                f"total_assets={assets}; total_liabilities={liabilities}; "
                f"equity={equity}; difference={difference}; tolerance={tolerance}"
            ),
            "detected_at": utc_now(),
        })
    return issues
