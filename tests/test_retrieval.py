"""Phase 3 unstructured retrieval tests."""
import pytest

from documents.generate_documents import write_pdf
from retrieval import DocumentStore, clean_text, find_plates


@pytest.fixture(scope="module")
def store():
    return DocumentStore()  # the real synthetic repository under documents/


@pytest.fixture
def tiny_repo(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "one.txt").write_text(
        "Document ID: T-1\nDocument Type: Theft Complaint\nDate: 2024-01-05\nRegistration Number: KA 01 AB 1234\n"
        "Make: Honda\nModel: City\n\n" + " ".join(f"word{i}" for i in range(150)) + " stolen near the market", encoding="utf-8")
    (tmp_path / "a" / "two.md").write_text("# Notice\n\nDate: 2024-02-01\nGeneral notice about HSRP plates in Karnataka.",
                                           encoding="utf-8")
    (tmp_path / "a" / "three.html").write_text("<html><body><p>Registration Number: MH12XY0001</p>"
                                               "<p>Inspection report, odometer 1200 km</p></body></html>", encoding="utf-8")
    write_pdf(str(tmp_path / "a" / "four.pdf"), "Document ID: T-4\nRegistration Number: TN01ZZ9999\nPolicy Number: POL-T-4\n"
              "Policy schedule text", "Test policy", "T-4")
    (tmp_path / "a" / "broken.pdf").write_bytes(b"not a pdf")
    (tmp_path / "a" / "ignored.csv").write_text("x,y", encoding="utf-8")
    return DocumentStore(str(tmp_path), chunk_words=60, overlap=15)


def test_loading_supports_txt_md_html_pdf_and_reports_errors(tiny_repo):
    stats = tiny_repo.stats()
    assert stats["documents"] == 4
    assert stats["formats"] == {"txt": 1, "md": 1, "html": 1, "pdf": 1}
    assert len(stats["errors"]) == 1 and "broken.pdf" in stats["errors"][0]["path"]


def test_text_extraction_and_cleaning(tiny_repo):
    pdf = tiny_repo.get("T-4")
    assert "POL-T-4" in pdf["text"] and pdf["metadata"]["pages"] == 1
    html = next(d for d in tiny_repo.list_documents() if d["format"] == "html")
    assert "<p>" not in tiny_repo.get(html["doc_id"])["text"]
    assert clean_text("a b – c\r\n\n\n\nd") == "a b - c\n\nd"


def test_chunking_uses_overlapping_windows(tiny_repo):
    chunks = tiny_repo.get("T-1")["chunks"]
    assert len(chunks) >= 3
    first, second = chunks[0]["text"].split(), chunks[1]["text"].split()
    assert first[-15:] == second[:15]  # 15-word overlap


def test_metadata_extraction(tiny_repo, store):
    m = tiny_repo.get("T-1")["metadata"]
    assert m["document_type"] == "Theft Complaint" and m["document_type_source"] == "header"
    assert m["registration_numbers"] == ["KA01AB1234"] and m["date"] == "2024-01-05"
    assert tiny_repo.get("T-4")["metadata"]["identifiers"]["policy_numbers"] == ["POL-T-4"]
    inv = store.documents["DOC-POL-INV-001"].metadata
    assert inv["document_type_source"] == "inferred" and inv["document_type"] == "Police Investigation Report"
    assert inv["noisy_plate_mentions"] == [{"raw": "GJO1AB7777", "corrected": "GJ01AB7777"}]
    assert all(d["synthetic"] for d in store.list_documents())


def test_plate_detection_variants_and_no_false_positives():
    plates, noisy = find_plates("Seen DL-01-AB-1234, then 22 BH 1234 AA; challan ECH-MH12-2024-77812; ANPR read DLO1AB1234")
    assert plates == ["DL01AB1234", "22BH1234AA"]
    assert noisy == [{"raw": "DLO1AB1234", "corrected": "DL01AB1234"}]


def test_index_and_bm25_ranking(store):
    stats = store.stats()
    assert stats["documents"] == 37 and stats["formats"] == {"txt": 20, "pdf": 12, "md": 5} and not stats["errors"]
    hits = store.search("theft claim repudiated policy inception")
    assert hits[0]["doc_id"] == "DOC-INS-CLM-002"
    assert [h["bm25"] for h in hits] == sorted([h["bm25"] for h in hits], reverse=True)


def test_metadata_filtering(store):
    hits = store.search("certificate", document_type="Registration Certificate")
    assert hits and all(h["metadata"]["document_type"] == "Registration Certificate" for h in hits)
    hits = store.search("insurance", registration_number="dl 01 ab 1234")
    assert hits and all("DL01AB1234" in h["metadata"]["registration_numbers"] for h in hits)


def _ctx(**kw):
    base = {"plate": "DL01AB1234", "intents": ["FULL_HISTORY"], "facts": {"make": "Honda", "model": "City", "state": "Delhi"},
            "identifiers": {}, "names": [], "organisations": [], "dates": []}
    base.update(kw)
    return base


def test_context_based_retrieval_ranks_identifier_matches_first(store):
    r = store.retrieve_for_context(_ctx(identifiers={"claim_numbers": ["CLM-HDFC-2026-0412"], "policy_numbers": ["POL-HDFC-9901"]},
                                        dates=["2026-03-18"]))
    assert r["documents"][0]["doc_id"] == "DOC-INS-CLM-001"
    assert all(d["scope"] == "vehicle_specific" for d in r["documents"])
    assert {d["doc_id"] for d in r["documents"]} >= {"DOC-INS-POL-001", "DOC-RC-001", "DOC-INSP-001"}
    top = r["documents"][0]
    assert top["score_breakdown"]["identifiers"] == 1.0 and any("Shares identifier" in x for x in top["reasons"])


def test_lookalike_plate_document_is_rejected_by_structured_context(store):
    r = store.retrieve_for_context(_ctx())
    assert "DOC-INSP-005" not in {d["doc_id"] for d in r["documents"]}
    rejected = next(x for x in r["rejected"] if x["doc_id"] == "DOC-INSP-005")
    assert "different vehicle" in rejected["reason"]
    # Without contradicting context the same document is NOT rejected (context is what decides)
    r2 = store.retrieve_for_context(_ctx(facts={"state": "Delhi"}))
    assert "DOC-INSP-005" in {d["doc_id"] for d in r2["documents"]}


def test_ocr_noisy_document_mention_is_retrieved(store):
    r = store.retrieve_for_context(_ctx(plate="GJ01AB7777", intents=["THEFT"], facts={"make": "Mahindra", "model": "XUV700",
                                                                                      "theft_status": "STOLEN"}))
    inv = next(d for d in r["documents"] if d["doc_id"] == "DOC-POL-INV-001")
    assert inv["match_kind"] == "ocr_noisy" and "GJO1AB7777" in inv["reasons"][0]


def test_status_and_intent_drive_expected_types_and_general_notices(store):
    r = store.retrieve_for_context(_ctx(plate="MH12DE1432", intents=["INSURANCE"],
                                        facts={"make": "Tata", "model": "Nexon", "state": "Maharashtra", "insurance_status": "EXPIRED"}))
    assert "Compliance Notice" in r["expected_document_types"]
    assert {d["doc_id"] for d in r["documents"]} >= {"DOC-COMP-002", "DOC-INS-POL-002"}
    assert [g["doc_id"] for g in r["general_documents"]] == ["DOC-RTO-NOT-005"]
    assert r["general_documents"][0]["scope"] == "general"


def test_no_document_case_returns_nothing_rather_than_guessing(store):
    r = store.retrieve_for_context(_ctx(plate="PB10AB5050", facts={"make": "Mahindra", "model": "Thar", "state": "Punjab"}))
    assert r["documents"] == [] and r["general_documents"] == []


def test_evidence_checks_compare_documents_with_database_values(store):
    r = store.retrieve_for_context(_ctx(plate="KA05MJ5555", facts={"make": "Maruti Suzuki", "model": "Swift", "colour": "Crimson Red"},
                                        fact_alternatives={"colour": [{"value": "Fire Red", "source": "registration_authority"}]}))
    doc = next(d for d in r["documents"] if d["doc_id"] == "DOC-INSP-002")
    colour = next(c for c in doc["evidence_checks"] if c["field"] == "colour")
    assert colour["status"] == "SUPPORTS_ALTERNATIVE" and colour["supported_source"] == "registration_authority"
    r = store.retrieve_for_context(_ctx(plate="KA05MJ5555", facts={"make": "Maruti Suzuki", "model": "Swift", "colour": "Blue"}))
    doc = next(d for d in r["documents"] if d["doc_id"] == "DOC-INSP-002")
    assert next(c for c in doc["evidence_checks"] if c["field"] == "colour")["status"] == "CONFLICTS"


def test_structured_and_unstructured_integration_in_federated_result():
    import asyncio
    from federation import run_federated_query
    from tests.federation_helpers import RouterTransport, TEST_URLS, service_apps
    r = asyncio.run(run_federated_query("Is WB02K0001 scrapped?", urls=TEST_URLS, transport=RouterTransport(service_apps())))
    used = r["documents"]["context_used"]
    assert used["identifiers"]["certificate_numbers"] == ["COD-WB-2021-00087"]  # came from the theft DB
    assert r["documents"]["documents"][0]["doc_id"] == "DOC-SCRAP-001"
    kinds = [s["kind"] for s in r["answer"]["statements"]]
    assert "database_fact" in kinds and "document_evidence" in kinds and "conflict" in kinds
    docs_stmt = [s for s in r["answer"]["statements"] if s["kind"] == "document_evidence"]
    assert all(s["sources"][0].startswith("document:") for s in docs_stmt)


def test_gateway_document_endpoints():
    from fastapi.testclient import TestClient
    import gateway
    client = TestClient(gateway.app)
    listing = client.get("/api/documents").json()
    assert listing["stats"]["documents"] == 37
    doc = client.get("/api/documents/DOC-FIR-001").json()
    assert doc["metadata"]["identifiers"]["fir_numbers"] == ["GJ-NAV-2023-0457"]
    assert client.get("/api/documents/NOPE").status_code == 404
    hits = client.post("/api/documents/search", json={"query": "scrapping certificate", "top_k": 3}).json()
    assert hits[0]["metadata"]["document_type"] == "Scrapping Certificate"
