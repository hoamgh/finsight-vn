"""Local, persistent and citation-preserving RAG for the FinSight MVP."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


INDEX_VERSION = "local-hashing-v1"
EXTRACTION_CONFIG_VERSION = "docling-ocr-v3-physical-pages"
DEFAULT_OCR_PROFILE = "rapidocr"
PAGE_NUMBERING = "physical_one_based"
DEFAULT_DIMENSIONS = 4096
TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
QUERY_EXPANSIONS = {
    "risk": "rui ro",
    "risks": "rui ro",
    "revenue": "doanh thu",
    "cash": "tien",
    "investment": "dau tu",
    "investments": "dau tu",
    "loan": "vay",
    "loans": "vay",
    "debt": "no vay",
    "accounting": "ke toan",
    "policy": "chinh sach",
    "policies": "chinh sach",
    "related party": "ben lien quan",
    "technology": "cong nghe",
    "software": "phan mem",
    "management": "ban lanh dao",
    "segment": "bo phan linh vuc",
}
GROUNDING_STOPWORDS = {
    "bao", "cao", "cho", "cua", "fpt", "nam", "nay", "nhung", "the", "what",
    "which", "with", "does", "did", "duoc", "trong", "tai", "mot", "cac", "khong",
    "2023", "2024", "2025", "2026", "quy",
}


class DocumentExtractionError(RuntimeError):
    pass


class ExperimentalOcrDependencyError(DocumentExtractionError):
    pass


@dataclass(frozen=True)
class DocumentMetadata:
    document_id: str
    symbol: str
    period: str
    report_type: str
    statement_basis: str
    source: str
    source_reference: str
    source_sha256: str
    extracted_at: str
    extraction_method: str = "docling"


@dataclass(frozen=True)
class DocumentElement:
    page: int | None
    section: str
    element_type: str
    text: str


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    document_id: str
    symbol: str
    period: str
    page: int | None
    section: str
    chunk_type: str
    parent_ref: str
    source_reference: str
    text: str


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: Chunk
    score: float


@dataclass(frozen=True)
class Citation:
    chunk_id: str
    symbol: str
    document_id: str
    period: str
    page: int | None
    section: str
    source_reference: str


@dataclass(frozen=True)
class RagResponse:
    answer: str
    citations: tuple[Citation, ...]
    evidence: tuple[RetrievedChunk, ...]
    sufficient: bool


def normalize_for_search(text: str) -> str:
    value = unicodedata.normalize("NFKD", text.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", value.replace("đ", "d")).strip()


def source_digest(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extraction_config(profile: str = DEFAULT_OCR_PROFILE) -> dict[str, Any]:
    """Return the complete, stable extraction identity used by the cache."""
    if profile not in {"rapidocr", "easyocr_vi", "hybrid_vi"}:
        raise ValueError(f"Unsupported OCR profile: {profile}")
    versions = {
        name: importlib.metadata.version(name)
        for name in ("docling", "docling-core", "rapidocr", "torch")
    }
    if profile in {"easyocr_vi", "hybrid_vi"}:
        try:
            versions["easyocr"] = importlib.metadata.version("easyocr")
        except importlib.metadata.PackageNotFoundError as error:
            raise ExperimentalOcrDependencyError(
                "The experimental easyocr_vi and hybrid_vi profiles require the optional "
                "EasyOCR package. Install easyocr explicitly in a development environment."
            ) from error
    return {
        "version": EXTRACTION_CONFIG_VERSION,
        "profile": profile,
        "versions": versions,
        "rapidocr": {"backend": "torch", "lang": ["chinese"], "mode": "default"},
        "easyocr": ({"lang": ["vi", "en"], "mode": "layout_regions"}
                    if profile in {"easyocr_vi", "hybrid_vi"} else None),
        "table_source": "rapidocr" if profile == "hybrid_vi" else profile,
    }


def extraction_config_digest(config: dict[str, Any]) -> str:
    encoded = json.dumps(config, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def physical_page_number(item: Any) -> int | None:
    """Return Docling's physical, one-based PDF page number unchanged."""
    provenance = getattr(item, "prov", None)
    return provenance[0].page_no if provenance else None


def _cache_is_current(payload: dict[str, Any], source_sha256: str, config_sha256: str) -> bool:
    return (
        payload.get("page_numbering") == PAGE_NUMBERING
        and payload.get("metadata", {}).get("source_sha256") == source_sha256
        and payload.get("extraction_config_sha256") == config_sha256
    )


def _document_id(symbol: str, period: str, digest: str) -> str:
    return f"{symbol.upper()}-{period}-{digest[:12]}"


def extract_with_docling(
    pdf_path: str | Path,
    cache_path: str | Path,
    *,
    symbol: str,
    period: str,
    report_type: str = "quarterly_financial_statements",
    statement_basis: str = "consolidated",
    source: str = "official_fpt",
    ocr_profile: str = DEFAULT_OCR_PROFILE,
) -> tuple[DocumentMetadata, list[DocumentElement]]:
    """Extract a structured document once and reuse the content-addressed cache."""
    source_path = Path(pdf_path).resolve()
    destination = Path(cache_path).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"PDF not found: {source_path}")
    digest = source_digest(source_path)
    config = extraction_config(ocr_profile)
    config_digest = extraction_config_digest(config)
    if destination.is_file():
        payload = json.loads(destination.read_text(encoding="utf-8"))
        if _cache_is_current(payload, digest, config_digest):
            return (
                DocumentMetadata(**payload["metadata"]),
                [
                    DocumentElement(
                        page=element["page"],
                        section=element["section"],
                        element_type=element["element_type"],
                        text=element["text"],
                    )
                    for element in payload["elements"]
                ],
            )

    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import (
            EasyOcrOptions, OcrMode, PdfPipelineOptions, RapidOcrOptions,
        )
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling_core.types.doc import TableItem
    except ImportError as error:
        raise DocumentExtractionError("Docling is required for document extraction.") from error

    try:
        def converter(profile: str) -> Any:
            options = PdfPipelineOptions()
            options.do_ocr = True
            if profile == "rapidocr":
                options.ocr_options = RapidOcrOptions(
                    backend="torch", lang=["chinese"], mode=OcrMode.DEFAULT
                )
            else:
                options.ocr_options = EasyOcrOptions(
                    lang=["vi", "en"], mode=OcrMode.LAYOUT_REGIONS
                )
            return DocumentConverter(format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=options)
            })

        if ocr_profile == "hybrid_vi":
            rapid_document = converter("rapidocr").convert(source_path).document
            document = converter("easyocr_vi").convert(source_path).document
            rapid_tables: dict[int | None, list[str]] = {}
            for rapid_item, _level in rapid_document.iterate_items():
                if isinstance(rapid_item, TableItem):
                    rapid_page = physical_page_number(rapid_item)
                    rapid_tables.setdefault(rapid_page, []).append(
                        rapid_item.export_to_markdown(doc=rapid_document).strip()
                    )
        else:
            document = converter(ocr_profile).convert(source_path).document
            rapid_tables = {}
        elements: list[DocumentElement] = []
        section = "Document"
        for item, _level in document.iterate_items():
            label = str(getattr(item, "label", "unknown"))
            page = physical_page_number(item)
            if label in {"page_header", "page_footer"}:
                continue
            if label in {"title", "section_header"}:
                value = str(getattr(item, "text", "")).strip()
                if value:
                    section = value
                    elements.append(DocumentElement(page, section, "heading", value))
                continue
            if isinstance(item, TableItem):
                candidates = rapid_tables.get(page, [])
                value = (candidates.pop(0) if candidates
                         else item.export_to_markdown(doc=document).strip())
                element_type = "table"
            else:
                value = str(getattr(item, "text", "")).strip()
                element_type = "paragraph"
            if value:
                elements.append(DocumentElement(page, section, element_type, value))
    except Exception as error:
        raise DocumentExtractionError(f"Docling failed to extract {source_path}") from error

    metadata = DocumentMetadata(
        document_id=_document_id(symbol, period, digest),
        symbol=symbol.upper(),
        period=period,
        report_type=report_type,
        statement_basis=statement_basis,
        source=source,
        source_reference=str(source_path),
        source_sha256=digest,
        extracted_at=datetime.now(timezone.utc).isoformat(),
    )
    payload = {
        "metadata": asdict(metadata), "page_numbering": PAGE_NUMBERING,
        "extraction_config": config,
        "extraction_config_sha256": config_digest,
        "elements": [asdict(item) for item in elements],
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(destination)
    return metadata, elements


def _make_chunk(metadata: DocumentMetadata, element: DocumentElement, ordinal: int) -> Chunk:
    context = f"Section: {element.section}\n{element.text}" if element.section else element.text
    identity = "|".join(
        [metadata.document_id, str(element.page), element.section, element.element_type, context, str(ordinal)]
    )
    chunk_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    parent = hashlib.sha256(
        f"{metadata.document_id}|{element.section}".encode("utf-8")
    ).hexdigest()[:16]
    return Chunk(
        chunk_id=chunk_id,
        document_id=metadata.document_id,
        symbol=metadata.symbol,
        period=metadata.period,
        page=element.page,
        section=element.section,
        chunk_type=element.element_type,
        parent_ref=f"section:{parent}",
        source_reference=metadata.source_reference,
        text=context,
    )


def hierarchical_chunks(
    metadata: DocumentMetadata,
    elements: Iterable[DocumentElement],
    *,
    max_chars: int = 1800,
) -> list[Chunk]:
    """Keep tables standalone and group nearby paragraphs under their section/page."""
    chunks: list[Chunk] = []
    buffer: list[str] = []
    buffered: DocumentElement | None = None

    def flush() -> None:
        nonlocal buffer, buffered
        if buffered and buffer:
            merged = DocumentElement(
                buffered.page, buffered.section, "paragraph", "\n".join(buffer)
            )
            chunks.append(_make_chunk(metadata, merged, len(chunks)))
        buffer, buffered = [], None

    for element in elements:
        if element.element_type in {"table", "heading"}:
            flush()
            chunks.append(_make_chunk(metadata, element, len(chunks)))
            continue
        changed_context = buffered and (
            buffered.page != element.page or buffered.section != element.section
        )
        too_large = buffer and sum(len(item) for item in buffer) + len(element.text) > max_chars
        if changed_context or too_large:
            flush()
        buffered = element
        buffer.append(element.text)
    flush()
    return chunks


def save_chunks(chunks: Iterable[Chunk], path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        "".join(json.dumps(asdict(chunk), ensure_ascii=False) + "\n" for chunk in chunks),
        encoding="utf-8",
    )
    return destination


def _features(text: str) -> Counter[str]:
    normalized = normalize_for_search(text)
    tokens = TOKEN_RE.findall(normalized)
    features = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
    compact = normalized.replace(" ", "")
    features.extend(f"#{compact[index:index + 4]}" for index in range(max(0, len(compact) - 3)))
    return Counter(features)


def _expand_query(question: str) -> str:
    expanded = question
    lowered = normalize_for_search(question)
    for english, vietnamese in QUERY_EXPANSIONS.items():
        if english in lowered:
            expanded += " " + vietnamese
    return expanded


def _hash(feature: str, dimensions: int) -> str:
    value = int.from_bytes(hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest(), "big")
    return str(value % dimensions)


class LocalVectorIndex:
    """Persistent sparse hashing-vector index with corpus IDF weighting."""

    def __init__(self, chunks: list[Chunk], vectors: list[dict[str, float]], idf: dict[str, float], dimensions: int):
        self.chunks = chunks
        self.vectors = vectors
        self.idf = idf
        self.dimensions = dimensions

    @classmethod
    def build(cls, chunks: Iterable[Chunk], dimensions: int = DEFAULT_DIMENSIONS) -> "LocalVectorIndex":
        items = list(chunks)
        counts = [_features(chunk.text) for chunk in items]
        document_frequency: Counter[str] = Counter()
        for features in counts:
            document_frequency.update(set(features))
        idf = {
            feature: math.log((1 + len(items)) / (1 + frequency)) + 1
            for feature, frequency in document_frequency.items()
        }
        vectors = [cls._vector(features, idf, dimensions) for features in counts]
        return cls(items, vectors, idf, dimensions)

    @staticmethod
    def _vector(features: Counter[str], idf: dict[str, float], dimensions: int) -> dict[str, float]:
        vector: Counter[str] = Counter()
        for feature, frequency in features.items():
            vector[_hash(feature, dimensions)] += (1 + math.log(frequency)) * idf.get(feature, 1.0)
        norm = math.sqrt(sum(value * value for value in vector.values())) or 1.0
        return {key: value / norm for key, value in vector.items()}

    def save(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": INDEX_VERSION,
            "dimensions": self.dimensions,
            "idf": self.idf,
            "chunks": [asdict(chunk) for chunk in self.chunks],
            "vectors": self.vectors,
        }
        destination.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return destination

    @classmethod
    def load(cls, path: str | Path) -> "LocalVectorIndex":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("version") != INDEX_VERSION:
            raise ValueError("RAG index version is incompatible; rebuild the index.")
        return cls(
            [Chunk(**chunk) for chunk in payload["chunks"]],
            payload["vectors"],
            payload["idf"],
            payload["dimensions"],
        )

    def retrieve(
        self,
        question: str,
        *,
        symbol: str | None = None,
        period: str | None = None,
        top_k: int = 5,
    ) -> list[RetrievedChunk]:
        expanded = _expand_query(question)
        query = self._vector(_features(expanded), self.idf, self.dimensions)
        query_tokens = set(TOKEN_RE.findall(normalize_for_search(expanded))) - GROUNDING_STOPWORDS
        asks_for_amount = any(term in normalize_for_search(question) for term in ("bao nhieu", "how much"))
        ranked = []
        for chunk, vector in zip(self.chunks, self.vectors):
            if chunk.chunk_type == "heading":
                continue
            if symbol and chunk.symbol != symbol.upper():
                continue
            if period and chunk.period != period:
                continue
            score = sum(value * vector.get(key, 0.0) for key, value in query.items())
            if score > 0:
                chunk_tokens = set(TOKEN_RE.findall(normalize_for_search(chunk.text)))
                overlap = len(query_tokens & chunk_tokens)
                ranking_score = score + 0.01 * overlap
                if asks_for_amount and chunk.chunk_type == "table":
                    ranking_score += 0.02
                ranked.append((ranking_score, RetrievedChunk(chunk, score)))
        return [
            item for _, item in sorted(
                ranked, key=lambda pair: (-pair[0], -pair[1].score, pair[1].chunk.chunk_id)
            )[:top_k]
        ]


def _citation(chunk: Chunk) -> Citation:
    return Citation(
        chunk.chunk_id, chunk.symbol, chunk.document_id, chunk.period,
        chunk.page, chunk.section, chunk.source_reference,
    )


def grounded_answer(
    question: str,
    index: LocalVectorIndex,
    *,
    symbol: str | None = None,
    period: str | None = None,
    top_k: int = 5,
    min_score: float = 0.13,
) -> RagResponse:
    """Return an extractive answer only when retrieved report evidence is strong enough."""
    evidence = tuple(index.retrieve(question, symbol=symbol, period=period, top_k=top_k))
    informative = tuple(
        item for item in evidence
        if item.chunk.chunk_type != "heading" and len(item.chunk.text) >= 80
    )
    query_tokens = {
        token for token in TOKEN_RE.findall(normalize_for_search(_expand_query(question)))
        if len(token) >= 3 and token not in GROUNDING_STOPWORDS
    }
    best_tokens = set(TOKEN_RE.findall(normalize_for_search(informative[0].chunk.text))) if informative else set()
    grounded_overlap = len(query_tokens & best_tokens)
    if not informative or informative[0].score < min_score or grounded_overlap < 2:
        return RagResponse(
            "The indexed financial reports do not contain sufficient evidence to answer this question.",
            (), evidence, False,
        )
    # The local extractive baseline favors one precise passage over combining
    # a second, merely similar financial note into a potentially misleading answer.
    selected = [informative[0]]
    if len(informative) > 1:
        second = informative[1]
        if second.chunk.page == informative[0].chunk.page and second.score >= informative[0].score * 0.75:
            selected.append(second)
    passages = []
    citations = []
    for rank, item in enumerate(selected, start=1):
        text = re.sub(r"\s+", " ", item.chunk.text).strip()
        passages.append(f"[{rank}] {text[:700]}")
        citations.append(_citation(item.chunk))
    answer = "Report evidence: " + " ".join(passages)
    return RagResponse(answer, tuple(citations), evidence, True)
