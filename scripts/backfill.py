"""Run FPT financial backfill, reconciliation, official fallback, and warehouse load."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from finsight_vn.data_quality import completeness_issues, reconcile
from finsight_vn.ingestion import ingest_cafef, ingest_vnstock
from finsight_vn.normalization import normalize_official_extraction
from finsight_vn.warehouse import load_postgres, save_canonical_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="FPT")
    parser.add_argument("--start", default="2023Q1")
    parser.add_argument("--end", required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--official-json", type=Path)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--db-env-file", type=Path, default=Path(".env.postgres"))
    parser.add_argument("--skip-vnstock", action="store_true")
    args = parser.parse_args()

    cafef = ingest_cafef(args.symbol, args.start, args.end, args.data_root / "raw" / "financial")
    vnstock = []
    if not args.skip_vnstock:
        api_key = None
        if args.env_file.exists():
            for line in args.env_file.read_text(encoding="utf-8-sig").splitlines():
                if line.strip().startswith("VNSTOCK_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
        vnstock = ingest_vnstock(
            args.symbol, args.start, args.end,
            args.data_root / "raw" / "financial", api_key=api_key,
        )
    official = []
    if args.official_json and args.official_json.exists():
        payload = json.loads(args.official_json.read_text(encoding="utf-8"))
        official = normalize_official_extraction(payload, str(args.official_json.resolve()))

    records, reconciliation = reconcile(
        cafef, vnstock, official=official, prefer_secondary=True
    )
    missing = completeness_issues(records, args.start, args.end, "cafef+official_fallback")
    canonical_path = args.data_root / "canonical" / f"{args.symbol.lower()}_financial.jsonl"
    save_canonical_jsonl(canonical_path, records)
    database_url = None
    if args.db_env_file.exists():
        for line in args.db_env_file.read_text(encoding="utf-8-sig").splitlines():
            if line.strip().startswith("FINSIGHT_DATABASE_URL="):
                database_url = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    if not database_url:
        raise RuntimeError("FINSIGHT_DATABASE_URL is missing from the database env file")
    load_postgres(database_url, records, [*reconciliation, *missing])
    print(f"canonical_records={len(records)}")
    print(f"quality_issues={len(reconciliation) + len(missing)}")
    print(f"canonical={canonical_path.resolve()}")
    print("warehouse=postgresql://localhost:5433/finsight")


if __name__ == "__main__":
    main()
