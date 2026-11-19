"""Phase 3 federation tests. Services are real FastAPI apps reached through the real httpx
async client; only the network socket is replaced by an in-process ASGI router."""
import asyncio
import datetime

import pytest

from federation import resolve_entity, run_federated_query
from query_engine import decompose_query, extract_plate, understand_query
from tests.federation_helpers import RouterTransport, TEST_URLS, service_apps

TODAY = datetime.date(2026, 11, 19)


@pytest.fixture(scope="module")
def apps():
    return service_apps()


def run(query, apps, plate=None, context=None, **kw):
    transport = kw.pop("transport", None) or RouterTransport(apps)
    result = asyncio.run(run_federated_query(query, plate=plate, context=context, urls=TEST_URLS,
                                             transport=transport, today=TODAY, **kw))
    return result, transport


# ----------------------------------------------------------------------------- understanding / decomposition
@pytest.mark.parametrize("text,plate", [
    ("Check the complete history of vehicle DL01AB1234.", "DL01AB1234"),
    ("is GJ 01 AB 7777 stolen", "GJ01AB7777"),
    ("ownership of UP16-BT-9900?", "UP16BT9900"),
    ("status of 22 BH 1234 AA", "22BH1234AA"),
    ("similar to DLO1AB1234", "DLO1AB1234"),
])
def test_plate_extraction_tolerates_formatting_and_ocr_noise(text, plate):
    assert understand_query(text)["registration_number"] == plate


def test_ocr_noisy_plate_gets_syntax_correction():
    u = understand_query("history of DLO1AB1234")
    assert u["plate_syntax_valid"] is False and u["plate_syntax_corrected"] == "DL01AB1234"
    assert extract_plate("no plate here at all") == {}


@pytest.mark.parametrize("text,expected,not_expected", [
    ("Check the complete history of vehicle DL01AB1234", {"vehicle_registry", "insurance_records", "registration_authority",
                                                          "theft_scrapping", "audit_log"}, set()),
    ("Is DL01AB1234 stolen?", {"vehicle_registry", "theft_scrapping"}, {"insurance_records", "audit_log", "registration_authority"}),
    ("Is DL01AB1234 insured?", {"vehicle_registry", "insurance_records"}, {"theft_scrapping", "audit_log", "registration_authority"}),
    ("Who owns DL01AB1234, any ownership transfer?", {"vehicle_registry", "registration_authority"}, {"insurance_records", "theft_scrapping"}),
    ("Show the audit history of KA05MJ5555", {"vehicle_registry", "audit_log"}, {"insurance_records", "theft_scrapping"}),
    ("Is this vehicle insured, stolen or scrapped? GJ01AB7777", {"insurance_records", "theft_scrapping", "registration_authority"}, {"audit_log"}),
])
def test_decomposition_selects_only_relevant_databases(text, expected, not_expected):
    d = decompose_query(understand_query(text))
    selected = set(d["selected_services"])
    assert expected <= selected
    assert not (not_expected & selected)
    assert {s["service"] for s in d["skipped"]} == {"vehicle_registry", "insurance_records", "registration_authority",
                                                    "theft_scrapping", "audit_log"} - selected
    assert all(s["reason"] for s in d["subqueries"])


def test_audit_subquery_is_wave_two_and_relations_follow_intent():
    d = decompose_query(understand_query("Is DL01AB1234 stolen?"))
    theft = next(s for s in d["subqueries"] if s["service"] == "theft_scrapping")
    assert "scrapping" not in theft["payload"]["include"] and "theft_reports" in theft["payload"]["include"]
    d = decompose_query(understand_query("complete history DL01AB1234"))
    assert next(s for s in d["subqueries"] if s["service"] == "audit_log")["wave"] == 2


# ----------------------------------------------------------------------------- execution
def test_single_database_query(apps):
    r, t = run("Is DL01AB1234 stolen?", apps)
    called = {c["service"] for c in r["context"]["subqueries"]}
    assert called == {"vehicle_registry", "theft_scrapping"}
    assert set(t.calls) == called
    assert r["context"]["attributes"]["theft_status"]["value"] == "CLEAR"
    assert r["integration"]["insurance_risk"]["status"] == "NOT_QUERIED"


def test_all_five_databases_complete_history(apps):
    r, _ = run("Check the complete history of vehicle DL01AB1234.", apps)
    statuses = {k: v["status"] for k, v in r["context"]["service_availability"].items()}
    assert statuses == {k: "ok" for k in TEST_URLS}
    res = r["context"]["database_results"]
    assert set(res) >= {"vehicle_registry", "insurance_records", "registration_authority", "theft_scrapping"}
    reg = res["vehicle_registry"][0]
    assert reg["related"]["manufacturer"]["name"] == "Honda"
    assert reg["related"]["owner"]["full_name"] == "Aarav Sharma"
    assert [v["registration_number"] for v in reg["related"]["owner_other_vehicles"]] == ["DL08CZ1010"]
    assert res["insurance_records"][0]["related"]["claims"][0]["claim_number"] == "CLM-HDFC-2026-0412"
    assert res["registration_authority"][0]["related"]["transfers"][0]["previous_owner"] == "Rohan Mehta"
    relations = {(p["source"], p["relation"]) for p in r["context"]["relationship_paths"]}
    assert ("vehicle_registry", "manufacturer") in relations and ("insurance_records", "claims") in relations
    assert r["integration"]["insurance_risk"]["status"] == "CURRENT"
    assert r["answer"]["headline"].startswith("DL01AB1234")
    kinds = {s["kind"] for s in r["answer"]["statements"]}
    assert {"database_fact", "assessment", "document_evidence"} <= kinds


def test_wave_one_runs_in_parallel(apps):
    slow = {k: 0.4 for k in ("vehicle_registry", "insurance_records", "registration_authority", "theft_scrapping")}
    r, _ = run("Check the complete history of vehicle DL01AB1234.", apps, transport=RouterTransport(apps, slow=slow),
               include_documents=False)
    wave1 = [c for c in r["context"]["subqueries"] if c["wave"] == 1]
    assert len(wave1) == 4 and all(c["latency_ms"] >= 400 for c in wave1)
    stage = next(s for s in r["stages"] if s["stage"].startswith("Federated Execution (wave 1"))
    assert stage["ms"] < 1200, "4 x 0.4 s sequentially would take >= 1.6 s"
    assert max(c["started_ms"] for c in wave1) < min(c["ended_ms"] for c in wave1)  # all in flight together


def test_audit_wave_two_uses_record_ids_discovered_in_wave_one(apps):
    r, _ = run("Show the full history and audit trail of KA05MJ5555", apps)
    audit_call = next(c for c in r["context"]["subqueries"] if c["service"] == "audit_log")
    assert audit_call["wave"] == 2
    refs = audit_call["payload"]["record_refs"]
    assert {"source": "vehicle_registry", "record_id": 3} in refs
    entries = r["context"]["audit_entries"]
    assert entries and entries[0]["field_name"] == "colour" and entries[0]["reviewer"] == "a.verma"


def test_noisy_plate_is_resolved_across_sources(apps):
    r, _ = run("Find vehicles with registration numbers similar to DLO1AB1234 and identify discrepancies", apps)
    ent = r["context"]["resolved_entity"]
    assert ent["registration_number"] == "DL01AB1234" and ent["query_plate"] == "DLO1AB1234"
    assert ent["confidence"] == "HIGH" and "Fuzzy resolution" in ent["method"]
    assert r["answer"]["statements"][0]["kind"] == "resolution"


def test_timeout_yields_partial_results(apps):
    r, _ = run("Is this vehicle insured, stolen or scrapped? GJ01AB7777", apps,
               transport=RouterTransport(apps, slow={"theft_scrapping": 2.0}), timeout=0.5)
    avail = r["context"]["service_availability"]
    assert avail["theft_scrapping"]["status"] == "timeout"
    assert avail["insurance_records"]["status"] == "ok"
    assert any("Theft & Scrapping" in m["item"] for m in r["missing_information"])
    assert any("NOT a clearance" in s["text"] for s in r["answer"]["statements"] if s["kind"] == "missing")
    assert "REPORTED STOLEN" not in r["answer"]["headline"]  # no theft evidence -> no theft claim either way


def test_unavailable_insurance_service_is_reported_not_guessed(apps):
    r, _ = run("Is DL01AB1234 insured?", apps, transport=RouterTransport(apps, down={"insurance_records"}))
    assert r["context"]["service_availability"]["insurance_records"]["status"] == "unavailable"
    assert r["integration"]["insurance_risk"]["status"] == "UNVERIFIED"
    assert r["context"]["attributes"]["make"]["value"] == "Honda"  # registry still answered
    assert any(m["item"] == "insurance status" for m in r["missing_information"])


def test_http_error_from_service(apps):
    r, _ = run("Who owns DL01AB1234?", apps, transport=RouterTransport(apps, http_error={"registration_authority"}))
    assert r["context"]["service_availability"]["registration_authority"]["status"] == "error"
    assert r["context"]["attributes"]["owner"]["value"] == "Aarav Sharma"


def test_all_services_down(apps):
    r, _ = run("complete history of DL01AB1234", apps, transport=RouterTransport(apps, down=set(TEST_URLS)))
    assert r["context"]["resolved_entity"]["registration_number"] is None
    assert "No vehicle" in r["answer"]["headline"]


@pytest.mark.parametrize("query,conflict_type", [
    ("ownership history and insurance details for UP16BT9900", "owner_mismatch"),
    ("Is WB02K0001 scrapped?", "scrapped_but_rc_valid"),
    ("Is this vehicle insured, stolen or scrapped? GJ01AB7777", "policy_after_theft"),
    ("Is AP09CA3322 insured?", "concurrent_policies"),
    ("full history of KA05MJ5555", "attribute_mismatch"),
])
def test_cross_database_conflicts_are_detected_with_evidence(apps, query, conflict_type):
    r, _ = run(query, apps)
    conflict = next(c for c in r["integration"]["conflicts"] if c["type"] == conflict_type)
    assert conflict["evidence"] and conflict["resolution"].startswith("UNRESOLVED")
    sources = {e["source"] for e in conflict["evidence"]}
    assert sources - {"document"}, "conflict must cite database records"


def test_conflict_explanation_and_document_support_never_auto_resolve(apps):
    r, _ = run("full history of KA05MJ5555", apps)
    colour = next(c for c in r["integration"]["conflicts"] if c["type"] == "attribute_mismatch")
    assert "COLOUR_CHANGE_ENDORSEMENT" in colour["explanation"]
    assert any(e["source"] == "document" and "registration_authority" in e.get("note", "") for e in colour["evidence"])
    assert r["context"]["attributes"]["colour"]["value"] == "Crimson Red"  # registry value is not overwritten
    assert r["integration"]["cleansing_proposals"][0]["proposed_value"] == "Fire Red"


def test_context_stays_relevant_to_the_query(apps):
    r, _ = run("Is DL01AB1234 stolen?", apps)
    res = r["context"]["database_results"]
    assert "insurance_records" not in res and "audit_log" not in res
    reg_related = res["vehicle_registry"][0]["related"]
    assert "owner_other_vehicles" not in reg_related  # ownership graph not needed for a theft question
    plates = {m["plate"] for m in r["context"]["matched_entities"]}
    assert plates == {"DL01AB1234"}


def test_entity_resolution_keeps_distinct_vehicles_apart():
    def call(service, plates):
        field = {"vehicle_registry": "registration_number", "registration_authority": "plate_identifier"}[service]
        return {"service": service, "status": "ok", "result": {"matches": [
            {"record": {field: p}, "record_id": i, "match": {"combined_score": s, "dl_similarity": s}}
            for i, (p, s) in enumerate(plates)]}}
    calls = [call("vehicle_registry", [("DL01AB1234", 1.0), ("DL01AB1243", 0.9)]),
             call("registration_authority", [("DL01AB1234", 1.0)])]
    ent = resolve_entity("DL01AB1234", calls)
    assert ent["cluster"] == ["DL01AB1234"]  # registry holds both -> two different vehicles
    calls = [call("vehicle_registry", [("DLO1AB1234", 1.0)]), call("registration_authority", [("DL01AB1234", 0.9)])]
    ent = resolve_entity("DL01AB1234", calls)
    assert set(ent["cluster"]) == {"DL01AB1234", "DLO1AB1234"}  # same vehicle, plate variant


def test_plate_variant_in_one_source_produces_conflict_and_proposal(apps):
    from fastapi.testclient import TestClient
    reg = TestClient(apps["vehicle_registry"])
    created = reg.post("/records", json={"registration_number": "MP04CC8B77", "make": "Hyundai", "model": "Venue",
                                         "colour": "Typhoon Silver", "vehicle_type": "Compact SUV",
                                         "registration_date": "2020-01-15", "state": "Madhya Pradesh"}).json()
    original = reg.get("/records", params={"query": "MP04CC8877"}).json()[0]
    reg.delete(f"/records/{original['id']}")
    try:
        r, _ = run("Find discrepancies for MP04CC8877", apps)
        assert r["context"]["resolved_entity"]["registration_number"] == "MP04CC8877"
        assert any(c["type"] == "plate_variant" for c in r["integration"]["conflicts"])
        props = r["integration"]["cleansing_proposals"]
        assert any(p["field_name"] == "registration_number" and p["proposed_value"] == "MP04CC8877" for p in props)
    finally:
        reg.delete(f"/records/{created['id']}")
        reg.post("/records", json={k: original[k] for k in ("registration_number", "make", "model", "colour",
                                                              "vehicle_type", "registration_date", "state")})


def test_query_without_plate_or_attributes_asks_for_plate(apps):
    r, t = run("hello, can you help?", apps)
    assert "No registration number" in r["error"] and t.calls == []


def test_attribute_only_query_uses_registry_attribute_search(apps):
    r, _ = run("Is the Mahindra XUV700 in Gujarat stolen?", apps)
    assert r["context"]["resolved_entity"]["registration_number"] == "GJ01AB7777"
    assert "Attribute search" in r["context"]["resolved_entity"]["method"]


def test_gateway_federated_endpoint(monkeypatch, apps):
    import gateway
    from fastapi.testclient import TestClient
    import federation

    original = federation.run_federated_query

    async def patched(*args, **kwargs):
        kwargs["transport"] = RouterTransport(apps)
        kwargs["urls"] = TEST_URLS
        return await original(*args, **kwargs)

    monkeypatch.setattr(federation, "run_federated_query", patched)
    client = TestClient(gateway.app)
    r = client.post("/api/federated-query", json={"query": "Is this vehicle stolen?", "plate": "gj01ab7777",
                                                  "plate_source": "ocr"}).json()
    assert r["understanding"]["plate_source"] == "ocr"
    assert "REPORTED STOLEN" in r["answer"]["headline"]
    u = client.post("/api/query/understand", json={"query": "insurance of DL01AB1234"}).json()
    assert u["decomposition"]["selected_services"] == ["vehicle_registry", "insurance_records"]
