"""Ask FinSight a structured or financial-document question."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from finsight_vn.agent import HybridQuestionError, ask
from finsight_vn.sql_agent import AgentQuestionError, UnsafeSqlError
from scripts.backfill_annual import env_value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question", required=True)
    parser.add_argument("--env-file", type=Path, default=Path(".env.postgres"))
    parser.add_argument("--index", type=Path, default=Path("data/rag/index.json"))
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    dsn = env_value(args.env_file, "FINSIGHT_DATABASE_URL")
    try:
        response = ask(
            args.question, dsn=dsn, index_path=args.index, top_k=args.top_k
        )
    except (AgentQuestionError, UnsafeSqlError, HybridQuestionError, FileNotFoundError) as error:
        raise SystemExit(f"Question rejected: {error}") from error
    print(f"Route: {response.route}")
    print(f"\nAnswer:\n{response.answer}")
    if response.sql:
        print("\nGenerated SQL:\n" + response.sql.sql)
        print("\nResult rows:\n" + json.dumps(response.sql.rows, default=str, ensure_ascii=False, indent=2))
    elif response.rag:
        print("\nSources:")
        for citation in response.rag.citations:
            page = f"page {citation.page}" if citation.page is not None else "page unavailable"
            print(f"- {citation.symbol} {citation.period}, {page}, {citation.section} [{citation.chunk_id}]")
        if args.debug:
            print("\nRetrieved evidence:")
            for item in response.rag.evidence:
                print(f"- score={item.score:.4f} chunk={item.chunk.chunk_id} page={item.chunk.page}")


if __name__ == "__main__":
    main()
