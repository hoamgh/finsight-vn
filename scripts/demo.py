"""Run the verified SQL and RAG interview questions through one router."""

from __future__ import annotations

import argparse
from pathlib import Path

from finsight_vn.agent import ask
from scripts.backfill_annual import env_value


DEMO_QUESTIONS = (
    "What was FPT revenue in 2025Q4?",
    "Compare FPT revenue in 2024Q4 and 2025Q4.",
    "How much did FPT net profit grow YoY in 2025Q4?",
    "Compare revenue growth for FPT, HPG, MWG and VNM in 2025Q4.",
    "What was FPT gross margin in 2025Q4?",
    "Show FPT operating cash flow from 2023Q1 through 2025Q4.",
    "Các khoản vay ngắn hạn của FPT được thực hiện theo hình thức nào?",
    "FPT giải thích nguyên nhân tăng trưởng quý 2 năm 2024 như thế nào?",
    "FPT kiểm soát Công ty Cổ phần Viễn thông FPT như thế nào?",
    "FPT có thảo luận rủi ro an ninh mạng không?",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env.postgres"))
    parser.add_argument("--index", type=Path, default=Path("data/rag/index.json"))
    args = parser.parse_args()
    dsn = env_value(args.env_file, "FINSIGHT_DATABASE_URL")
    if not dsn:
        raise SystemExit(f"FINSIGHT_DATABASE_URL is missing from {args.env_file}")
    for index, question in enumerate(DEMO_QUESTIONS, start=1):
        response = ask(question, dsn=dsn, index_path=args.index)
        print(f"\n[{index}] {question}")
        print(f"Route: {response.route}")
        print(f"Answer: {response.answer}")
        if response.sql:
            print("SQL:\n" + response.sql.sql)
        elif response.rag:
            for citation in response.rag.citations:
                print(
                    f"Source: {citation.symbol} {citation.period}, page {citation.page}, "
                    f"{citation.section} [{citation.chunk_id}]"
                )


if __name__ == "__main__":
    main()
