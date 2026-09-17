import json
from dataclasses import asdict
from types import SimpleNamespace

from finsight_vn.agent import ask, route_question
from finsight_vn.rag import (
    Chunk,
    DocumentElement,
    DocumentMetadata,
    LocalVectorIndex,
    extract_with_docling,
    extraction_config,
    extraction_config_digest,
    physical_page_number,
    grounded_answer,
    hierarchical_chunks,
    source_digest,
)


def metadata(digest="abc"):
    return DocumentMetadata(
        document_id="FPT-2024Q2-abc",
        symbol="FPT",
        period="2024Q2",
        report_type="quarterly_financial_statements",
        statement_basis="consolidated",
        source="official_fpt",
        source_reference="report.pdf",
        source_sha256=digest,
        extracted_at="2024-07-18T00:00:00+00:00",
    )


def sample_chunks():
    return hierarchical_chunks(
        metadata(),
        [
            DocumentElement(25, "Tiền và tương đương tiền", "heading", "Tiền và tương đương tiền"),
            DocumentElement(
                25, "Tiền và tương đương tiền", "paragraph",
                "Các khoản tương đương tiền là tiền gửi ngân hàng có kỳ hạn không quá 3 tháng.",
            ),
            DocumentElement(
                35, "Vay và nợ thuê tài chính", "table",
                "| Khoản vay ngắn hạn | VND |\n| Tín chấp ngân hàng | 100 |",
            ),
        ],
    )


def test_cached_docling_extraction_preserves_physical_page_number(tmp_path):
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"pdf")
    digest = source_digest(pdf)
    expected = metadata(digest)
    cache = tmp_path / "parsed.json"
    cache.write_text(
        json.dumps({
            "metadata": asdict(expected),
            "page_numbering": "physical_one_based",
            "extraction_config_sha256": extraction_config_digest(extraction_config()),
            "elements": [{"page": 9, "section": "Overview", "element_type": "paragraph", "text": "Evidence"}],
        }),
        encoding="utf-8",
    )
    loaded_metadata, elements = extract_with_docling(
        pdf, cache, symbol="FPT", period="2024Q2"
    )
    assert loaded_metadata == expected
    assert elements[0].page == 9
    assert elements[0].section == "Overview"


def test_extraction_cache_identity_changes_with_ocr_profile(monkeypatch):
    installed = {"docling": "2", "docling-core": "2", "rapidocr": "3", "torch": "4", "easyocr": "1"}
    monkeypatch.setattr("finsight_vn.rag.importlib.metadata.version", installed.__getitem__)
    rapid = extraction_config_digest(extraction_config("rapidocr"))
    hybrid = extraction_config_digest(extraction_config("hybrid_vi"))
    assert rapid != hybrid
    assert extraction_config("hybrid_vi")["easyocr"]["lang"] == ["vi", "en"]
    assert extraction_config("hybrid_vi")["table_source"] == "rapidocr"


def test_extraction_fingerprint_changes_with_runtime_version(monkeypatch):
    versions = {"docling": "2", "docling-core": "2", "rapidocr": "3", "torch": "4"}
    monkeypatch.setattr("finsight_vn.rag.importlib.metadata.version", versions.__getitem__)
    first = extraction_config_digest(extraction_config("rapidocr"))
    versions["torch"] = "5"
    second = extraction_config_digest(extraction_config("rapidocr"))
    assert first != second


def test_cache_identity_rejects_pdf_config_runtime_and_legacy_page_changes():
    from finsight_vn.rag import _cache_is_current

    payload = {
        "page_numbering": "physical_one_based",
        "metadata": {"source_sha256": "pdf-a"},
        "extraction_config_sha256": "config-a",
    }
    assert _cache_is_current(payload, "pdf-a", "config-a")
    assert not _cache_is_current(payload, "pdf-b", "config-a")
    assert not _cache_is_current(payload, "pdf-a", "config-b")
    assert not _cache_is_current({**payload, "page_numbering": "one_based"}, "pdf-a", "config-a")


def test_verified_physical_pages_survive_provenance_retrieval_and_citation():
    fixtures = (
        (9, "GIẢI TRÌNH", "Nguyên nhân tăng trưởng chủ yếu đến từ Khối công nghệ và thị trường Nhật Bản, Châu Á Thái Bình Dương.", "nguyên nhân tăng trưởng"),
        (30, "ĐẦU TƯ VÀO CÔNG TY CON", "Công ty Cổ phần Viễn thông FPT chịu quyền kiểm soát do Tập đoàn nắm đa số phiếu tại Hội đồng Quản trị.", "Viễn thông quyền kiểm soát"),
        (34, "VAY VÀ NỢ THUÊ TÀI CHÍNH", "Khoản vay ngắn hạn từ ngân hàng được thực hiện chủ yếu theo hình thức tín chấp và tín dụng thư bằng VND hoặc USD.", "vay tín chấp tín dụng thư"),
    )
    elements = []
    for page, section, text, _question in fixtures:
        item = SimpleNamespace(prov=[SimpleNamespace(page_no=page)])
        elements.append(DocumentElement(physical_page_number(item), section, "paragraph", text))
    index = LocalVectorIndex.build(hierarchical_chunks(metadata(), elements))
    for expected_page, _section, _text, question in fixtures:
        response = grounded_answer(question, index, symbol="FPT", min_score=0.01)
        assert response.sufficient
        assert response.evidence[0].chunk.page == expected_page
        assert response.citations[0].page == expected_page


def test_chunk_ids_and_metadata_are_deterministic():
    first = sample_chunks()
    second = sample_chunks()
    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]
    assert first[1].symbol == "FPT"
    assert first[1].period == "2024Q2"
    assert first[1].page == 25
    assert first[1].parent_ref.startswith("section:")


def test_index_persists_reloads_and_retrieves(tmp_path):
    path = tmp_path / "index.json"
    LocalVectorIndex.build(sample_chunks()).save(path)
    loaded = LocalVectorIndex.load(path)
    result = loaded.retrieve("Tiền gửi có kỳ hạn bao lâu?", symbol="FPT", top_k=2)
    assert result
    assert "không quá 3 tháng" in result[0].chunk.text
    assert loaded.chunks == LocalVectorIndex.load(path).chunks


def test_accented_and_unaccented_vietnamese_queries_keep_citations():
    index = LocalVectorIndex.build(sample_chunks())
    for question in (
        "Các khoản tương đương tiền có kỳ hạn bao lâu?",
        "Cac khoan tuong duong tien co ky han bao lau?",
    ):
        response = grounded_answer(question, index, symbol="FPT", min_score=0.05)
        assert response.sufficient
        assert response.citations[0].page == 25
        assert "không quá 3 tháng" in response.answer


def test_grounded_answer_propagates_citation_and_rejects_missing_evidence():
    index = LocalVectorIndex.build(sample_chunks())
    answer = grounded_answer(
        "Các khoản tương đương tiền có kỳ hạn bao lâu?", index, symbol="FPT", min_score=0.05
    )
    assert answer.sufficient
    assert answer.citations[0].page == 25
    assert answer.citations[0].chunk_id == answer.evidence[0].chunk.chunk_id
    missing = grounded_answer(
        "Phát thải carbon là bao nhiêu?", index, symbol="FPT", min_score=0.13
    )
    assert not missing.sufficient
    assert missing.citations == ()
    assert "sufficient evidence" in missing.answer


def test_router_classifies_sql_rag_and_hybrid():
    assert route_question("What was FPT revenue in 2025Q4?") == "SQL"
    assert route_question("What risks did FPT discuss in its report?") == "RAG"
    assert route_question("FPT revenue in 2025Q4: what did the report explain?") == "HYBRID"


def test_unified_agent_keeps_sql_route_working(tmp_path):
    def executor(_dsn, _sql):
        return ("symbol", "period", "revenue"), (("FPT", "2025Q4", 120),)

    response = ask(
        "What was FPT revenue in 2025Q4?",
        dsn="unused",
        index_path=tmp_path / "not-needed.json",
        sql_executor=executor,
    )
    assert response.route == "SQL"
    assert "revenue=120" in response.answer
