"""Backfill multi-company quarterly statements and load PostgreSQL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from finsight_vn.data_quality import (
    balance_sheet_identity_issues,
    completeness_issues,
    reconcile,
)
from finsight_vn.ingestion import ingest_vnstock
from finsight_vn.normalization import normalize_official_extraction
from finsight_vn.quarterly_ingestion import ingest_cafef_quarterly
from finsight_vn.warehouse import load_postgres, save_canonical_jsonl
from scripts.backfill_annual import env_value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=["FPT"])
    parser.add_argument("--start", default="2016Q1")
    parser.add_argument("--end", required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--db-env-file", type=Path, default=Path(".env.postgres"))
    parser.add_argument("--official-fpt-json", type=Path)
    parser.add_argument("--skip-vnstock", action="store_true")
    args = parser.parse_args()

    dsn = env_value(args.db_env_file, "FINSIGHT_DATABASE_URL")
    if not dsn:
        raise RuntimeError("FINSIGHT_DATABASE_URL is missing")
    api_key = env_value(args.env_file, "VNSTOCK_API_KEY")
    total = 0
    failures = []
    for symbol in args.symbols:
        try:
            cafef = ingest_cafef_quarterly(
                symbol, args.start, args.end, args.data_root / "raw" / "financial"
            )
            vci = [] if args.skip_vnstock else ingest_vnstock(
                symbol, args.start, args.end,
                args.data_root / "raw" / "financial", api_key=api_key,
            )
            official = []
            if symbol.upper() == "FPT" and args.official_fpt_json and args.official_fpt_json.exists():
                payload = json.loads(args.official_fpt_json.read_text(encoding="utf-8"))
                official = normalize_official_extraction(
                    payload, str(args.official_fpt_json.resolve())
                )
            records, issues = reconcile(
                cafef, vci, official=official, prefer_secondary=True
            )
            issues.extend(balance_sheet_identity_issues(vci))
            issues.extend(completeness_issues(records, args.start, args.end, "cafef+vci+official"))
            if not records:
                raise RuntimeError("No canonical quarterly records")
            path = args.data_root / "canonical" / f"{symbol.lower()}_financial_quarterly.jsonl"
            save_canonical_jsonl(path, records)
            load_postgres(dsn, records, issues)
            total += len(records)
            periods = sorted({f"{r.fiscal_year}Q{r.fiscal_quarter}" for r in records})
            print(f"{symbol.upper()}: periods={periods[0]}-{periods[-1]} records={len(records)} issues={len(issues)}")
        except Exception as error:
            failures.append(f"{symbol.upper()}: {type(error).__name__}: {error}")
            print(f"{symbol.upper()}: FAILED {type(error).__name__}: {error}")
    print(f"canonical_records={total}")
    print("warehouse=postgresql://localhost:5433/finsight")
    if failures:
        raise RuntimeError("Quarterly backfill failures: " + "; ".join(failures))


if __name__ == "__main__":
    main()
