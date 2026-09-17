"""Run the small retrieval and grounded-answer baseline evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from finsight_vn.rag import LocalVectorIndex, grounded_answer, normalize_for_search


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=Path("evaluation/rag_questions.json"))
    parser.add_argument("--index", type=Path, default=Path("data/rag/index.json"))
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    cases = json.loads(args.questions.read_text(encoding="utf-8"))
    index = LocalVectorIndex.load(args.index)
    retrieval_hits = 0
    answer_checks = 0
    citation_checks = 0
    for case in cases:
        response = grounded_answer(
            case["question"], index, symbol="FPT", period="2024Q2", top_k=args.top_k
        )
        evidence = normalize_for_search(" ".join(item.chunk.text for item in response.evidence))
        terms = [normalize_for_search(term) for term in case["expected_terms"]]
        if case["answerable"]:
            retrieval_hit = any(term in evidence for term in terms)
            answer_ok = response.sufficient and bool(response.citations)
            cited_ids = {citation.chunk_id for citation in response.citations}
            cited_text = normalize_for_search(" ".join(
                item.chunk.text for item in response.evidence if item.chunk.chunk_id in cited_ids
            ))
            citation_ok = any(term in cited_text for term in terms)
        else:
            retrieval_hit = not response.sufficient
            answer_ok = not response.sufficient
            citation_ok = not response.citations
        retrieval_hits += retrieval_hit
        answer_checks += answer_ok
        citation_checks += citation_ok
        print(
            f"{'PASS' if retrieval_hit and answer_ok and citation_ok else 'FAIL'} "
            f"retrieval={retrieval_hit} answer={answer_ok} citation={citation_ok} "
            f"question={case['question']}"
        )
    total = len(cases)
    print(f"retrieval_at_{args.top_k}={retrieval_hits}/{total}")
    print(f"grounded_answer={answer_checks}/{total}")
    print(f"citation_support={citation_checks}/{total}")


if __name__ == "__main__":
    main()
