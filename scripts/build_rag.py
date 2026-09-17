"""Extract one official PDF, create hierarchical chunks, and persist the local index."""

from __future__ import annotations

import argparse
from pathlib import Path

from finsight_vn.rag import (
    DEFAULT_OCR_PROFILE, LocalVectorIndex, extract_with_docling,
    hierarchical_chunks, save_chunks,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--period", required=True)
    parser.add_argument("--cache", type=Path, default=Path("data/parsed/fpt_2024q2.json"))
    parser.add_argument("--chunks", type=Path, default=Path("data/rag/fpt_2024q2_chunks.jsonl"))
    parser.add_argument("--index", type=Path, default=Path("data/rag/index.json"))
    parser.add_argument(
        "--ocr-profile", choices=("rapidocr", "easyocr_vi", "hybrid_vi"),
        default=DEFAULT_OCR_PROFILE,
        help=("OCR profile; rapidocr is production. easyocr_vi and hybrid_vi are "
              "experimental benchmarks requiring optional EasyOCR."),
    )
    args = parser.parse_args()
    metadata, elements = extract_with_docling(
        args.pdf, args.cache, symbol=args.symbol, period=args.period,
        ocr_profile=args.ocr_profile,
    )
    chunks = hierarchical_chunks(metadata, elements)
    save_chunks(chunks, args.chunks)
    LocalVectorIndex.build(chunks).save(args.index)
    print(f"document_id={metadata.document_id}")
    print(f"elements={len(elements)} chunks={len(chunks)}")
    print(f"cache={args.cache} index={args.index}")


if __name__ == "__main__":
    main()
