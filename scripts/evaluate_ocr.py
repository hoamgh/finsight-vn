"""Score the manually verified OCR sample set without correcting its evidence."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path


def distance(left: list[str], right: list[str]) -> int:
    previous = list(range(len(right) + 1))
    for row, left_item in enumerate(left, 1):
        current = [row]
        for column, right_item in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[column] + 1,
                               previous[column - 1] + (left_item != right_item)))
        previous = current
    return previous[-1]


def compact(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def without_diacritics(text: str) -> str:
    value = unicodedata.normalize("NFD", text.casefold()).replace("đ", "d")
    return "".join(char for char in value if not unicodedata.combining(char))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("evaluation/ocr_quality.json"))
    args = parser.parse_args()
    cases = json.loads(args.dataset.read_text(encoding="utf-8"))
    engines = list(cases[0]["extractions"])
    for engine in engines:
        chars = words = char_errors = word_errors = base_errors = 0
        number_total = number_hits = table_total = table_hits = 0
        for case in cases:
            expected = compact(case["expected_text"])
            actual = compact(case["extractions"][engine]["text"])
            chars += len(expected)
            words += len(expected.split())
            char_errors += distance(list(expected), list(actual))
            word_errors += distance(expected.split(), actual.split())
            base_expected, base_actual = without_diacritics(expected), without_diacritics(actual)
            base_errors += distance(list(base_expected), list(base_actual))
            expected_numbers = Counter(case["important_numbers"])
            actual_numbers = Counter({number: actual.count(number) for number in expected_numbers})
            number_total += sum(expected_numbers.values())
            number_hits += sum(min(count, actual_numbers[number]) for number, count in expected_numbers.items())
            shape = case["table_shape"]
            if shape:
                table_total += 1
                extraction = case["extractions"][engine]
                table_hits += extraction.get("rows") == shape["rows"] and extraction.get("columns") == shape["columns"]
        cer = char_errors / chars
        base_cer = base_errors / chars
        print(json.dumps({
            "engine": engine,
            "cer": round(cer, 4),
            "wer": round(word_errors / words, 4),
            "accent_error_component": round(max(0.0, cer - base_cer), 4),
            "accent_insensitive_cer": round(base_cer, 4),
            "important_number_exactness": f"{number_hits}/{number_total}",
            "table_shape_exactness": f"{table_hits}/{table_total}",
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
