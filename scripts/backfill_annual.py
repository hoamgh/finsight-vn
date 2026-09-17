"""Backfill structured annual financial statements from CafeF into PostgreSQL."""

from __future__ import annotations

import argparse
from pathlib import Path

from finsight_vn.annual_ingestion import (
    ingest_cafef_annual, ingest_vnstock_annual_cash_flow,
)
from finsight_vn.warehouse import load_postgres_annual, save_canonical_jsonl


def env_value(path: Path, name: str) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip().startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=["FPT"])
    parser.add_argument("--end-year", type=int, required=True)
    parser.add_argument("--start-year", type=int, default=2023)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--db-env-file", type=Path, default=Path(".env.postgres"))
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--skip-vnstock", action="store_true")
    args = parser.parse_args()

    dsn = env_value(args.db_env_file, "FINSIGHT_DATABASE_URL")
    if not dsn:
        raise RuntimeError("FINSIGHT_DATABASE_URL is missing")
    total = 0
    failures = []
    api_key = env_value(args.env_file, "VNSTOCK_API_KEY")
    for symbol in args.symbols:
        try:
            records = ingest_cafef_annual(
                symbol, args.start_year, args.end_year,
                args.data_root / "raw" / "financial",
            )
            if not args.skip_vnstock:
                fallback = ingest_vnstock_annual_cash_flow(
                    symbol, args.start_year, args.end_year,
                    args.data_root / "raw" / "financial", api_key=api_key,
                )
                merged = {record.key: record for record in fallback}
                merged.update({record.key: record for record in records})
                records = sorted(merged.values(), key=lambda record: record.key)
            if not records:
                raise RuntimeError("CafeF returned no canonical annual records")
            path = args.data_root / "canonical" / f"{symbol.lower()}_financial_annual.jsonl"
            save_canonical_jsonl(path, records)
            load_postgres_annual(dsn, records)
            years = sorted({record.fiscal_year for record in records})
            total += len(records)
            print(f"{symbol.upper()}: years={years[0]}-{years[-1]} records={len(records)}")
        except Exception as error:
            failures.append(f"{symbol.upper()}: {type(error).__name__}: {error}")
            print(f"{symbol.upper()}: FAILED {type(error).__name__}: {error}")
    print("period_type=annual")
    print(f"canonical_records={total}")
    print("warehouse=postgresql://localhost:5433/finsight")
    if failures:
        raise RuntimeError("Annual backfill failures: " + "; ".join(failures))


if __name__ == "__main__":
    main()
