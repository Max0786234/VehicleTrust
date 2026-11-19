import os
import pytest
from fastapi.testclient import TestClient

from service_registry import app as registry_app
from service_insurance import app as insurance_app
from service_registration import app as registration_app
from service_theft import app as theft_app
from gateway import app as gateway_app
import gateway as gateway_module
from matching import search_and_rank_candidates


@pytest.fixture
def gateway_client():
    return TestClient(gateway_app)


@pytest.fixture
def registry_client():
    return TestClient(registry_app)


@pytest.fixture
def insurance_client():
    return TestClient(insurance_app)


@pytest.fixture
def registration_client():
    return TestClient(registration_app)


@pytest.fixture
def theft_client():
    return TestClient(theft_app)


def test_registry_health(registry_client):
    resp = registry_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "vehicle_registry"
    assert "record_count" in data


def test_insurance_health(insurance_client):
    resp = insurance_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "insurance_records"


def test_registration_health(registration_client):
    resp = registration_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "registration_authority"


def test_theft_health(theft_client):
    resp = theft_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "theft_scrapping"


def test_registry_crud_lifecycle(registry_client):
    # 1. Create record
    test_plate = "DL99ZZ0001"
    payload = {
        "registration_number": test_plate,
        "make": "Volkswagen",
        "model": "Taigun",
        "colour": "Yellow",
        "vehicle_type": "SUV",
        "registration_date": "2024-02-01",
        "state": "Delhi",
    }
    create_resp = registry_client.post("/records", json=payload)
    assert create_resp.status_code == 201
    created = create_resp.json()
    rec_id = created["id"]
    assert created["registration_number"] == test_plate

    # 2. Get record
    get_resp = registry_client.get(f"/records/{rec_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["model"] == "Taigun"

    # 3. Update record
    put_resp = registry_client.put(f"/records/{rec_id}", json={"colour": "Curcuma Yellow"})
    assert put_resp.status_code == 200
    assert put_resp.json()["colour"] == "Curcuma Yellow"

    # 4. Search and verify matching engine sees the updated record
    records = registry_client.get("/records").json()
    ranked = search_and_rank_candidates(test_plate, [("vehicle_registry", records)])
    assert len(ranked) >= 1
    assert ranked[0]["raw_record"]["colour"] == "Curcuma Yellow"

    # 5. Delete record
    del_resp = registry_client.delete(f"/records/{rec_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True

    # 6. Verify 404 after deletion
    get_after_del = registry_client.get(f"/records/{rec_id}")
    assert get_after_del.status_code == 404


def test_insurance_crud_lifecycle(insurance_client):
    test_pol = "POL-TEST-XYZ"
    payload = {
        "policy_number": test_pol,
        "recorded_vehicle_number": "DL99ZZ0001",
        "insurer": "Digit General Insurance",
        "policy_start_date": "2026-01-01",
        "expiry_date": "2027-01-01",
        "policy_status": "ACTIVE",
    }
    c_resp = insurance_client.post("/records", json=payload)
    assert c_resp.status_code == 201
    pol_id = c_resp.json()["id"]

    # Verify duplicate policy number is rejected
    dup_resp = insurance_client.post("/records", json=payload)
    assert dup_resp.status_code == 400

    # Delete test policy
    d_resp = insurance_client.delete(f"/records/{pol_id}")
    assert d_resp.status_code == 200


def test_graceful_handling_unavailable_service():
    # Simulate partial failure: 1 service succeeds, 1 service is missing/offline
    available_records = [("vehicle_registry", [{"id": 1, "registration_number": "DL01AB1234"}])]
    # The search should operate smoothly with available data without throwing an exception
    ranked = search_and_rank_candidates("DL01AB1234", available_records)
    assert len(ranked) == 1
    assert ranked[0]["recorded_registration_number"] == "DL01AB1234"


def test_gateway_status_endpoint(gateway_client):
    resp = gateway_client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "services" in data


def test_gateway_status_includes_remote_audit_service(gateway_client, monkeypatch):
    import gateway as gateway_module

    monkeypatch.setattr(gateway_module, "AUDIT_API_URL", "http://audit-node:8105")

    class Response:
        status_code = 200

        def json(self):
            return {"record_count": 7}

    monkeypatch.setattr(gateway_module.httpx, "get", lambda url, timeout: Response())

    response = gateway_client.get("/api/status")

    assert response.status_code == 200
    assert response.json()["services"]["audit_log"]["online"] is True
    assert response.json()["services"]["audit_log"]["record_count"] == 7


def test_gateway_audit_logs_are_fetched_from_configured_service(gateway_client, monkeypatch):
    import gateway as gateway_module

    monkeypatch.setattr(gateway_module, "AUDIT_API_URL", "http://audit-node:8105")
    monkeypatch.setattr(
        gateway_module,
        "get_cleansing_audit_logs",
        lambda limit, source, url: [{"id": 1, "source": source, "url": url}],
    )

    response = gateway_client.get("/api/audit-logs?limit=5&source=vehicle_registry")

    assert response.status_code == 200
    assert response.json() == [{
        "id": 1,
        "source": "vehicle_registry",
        "url": "http://audit-node:8105",
    }]


def test_gateway_proxies_remote_crud_requests(gateway_client, monkeypatch):
    import gateway as gateway_module

    monkeypatch.setitem(gateway_module.DEFAULT_URLS, "vehicle_registry", "http://registry-node")
    forwarded = []

    class Response:
        status_code = 200
        is_success = True
        text = ""

        def json(self):
            return [{"id": 12, "registration_number": "DL01AB1234"}]

    def fake_request(method, url, json, timeout):
        forwarded.append((method, url, json))
        return Response()

    monkeypatch.setattr(gateway_module.httpx, "request", fake_request)

    list_response = gateway_client.get("/api/services/vehicle_registry/records")
    create_response = gateway_client.post(
        "/api/services/vehicle_registry/records",
        json={"registration_number": "DL01AB1234"},
    )
    delete_response = gateway_client.delete("/api/services/vehicle_registry/records/12")
    update_response = gateway_client.put(
        "/api/services/vehicle_registry/records/12",
        json={"colour": "Matte Black"},
    )

    assert list_response.status_code == 200
    assert create_response.status_code == 200
    assert delete_response.status_code == 200
    assert update_response.status_code == 200
    assert forwarded == [
        ("GET", "http://registry-node/records", None),
        ("POST", "http://registry-node/records", {"registration_number": "DL01AB1234"}),
        ("DELETE", "http://registry-node/records/12", None),
        ("PUT", "http://registry-node/records/12", {"colour": "Matte Black"}),
    ]


def test_gateway_rejects_unknown_database_service(gateway_client):
    response = gateway_client.get("/api/services/unknown/records")

    assert response.status_code == 404


def test_gateway_search_uses_observed_context_and_returns_cleansing_proposals(gateway_client, monkeypatch):
    service_records = {
        "8101": [{
            "id": 4,
            "registration_number": "DLO1AB1234",
            "make": "Honda",
            "model": "City",
            "colour": "White",
            "state": "Delhi",
        }],
        "8102": [],
        "8103": [{
            "id": 9,
            "plate_identifier": "DL01AB1234",
            "make": "Honda",
            "model": "City",
            "colour": "Pearl White",
            "state": "Delhi",
        }],
        "8104": [],
    }

    class Response:
        status_code = 200

        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    monkeypatch.setattr(
        gateway_module.httpx,
        "get",
        lambda url, timeout: Response(next(records for port, records in service_records.items() if f":{port}" in url)),
    )
    response = gateway_client.post(
        "/api/search",
        json={
            "query_plate": "DLO1AB1234",
            "make": "Honda",
            "model": "City",
            "colour": "White",
            "state": "Delhi",
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["candidates"][0]["recorded_registration_number"] == "DLO1AB1234"
    assert {(proposal["field_name"], proposal["proposed_value"]) for proposal in result["cleansing_proposals"]} == {
        ("registration_number", "DL01AB1234"),
        ("colour", "Pearl White"),
    }


def test_gateway_ocr_processes_image_and_returns_result(gateway_client, monkeypatch):
    processed = []

    def process_image(contents):
        processed.append(contents)
        return {
            "raw_text": "DLO1AB1234",
            "normalized_plate": "DLO1AB1234",
            "confidence": 0.91,
            "ocr_variants": ["DLO1AB1234", "DL01AB1234"],
            "message": "",
        }

    monkeypatch.setattr(gateway_module, "_process_ocr_image", process_image)

    response = gateway_client.post(
        "/api/ocr",
        files={"file": ("plate.jpg", b"image-bytes", "image/jpeg")},
    )

    assert response.status_code == 200
    assert response.json()["normalized_plate"] == "DLO1AB1234"
    assert processed == [b"image-bytes"]


def test_gateway_ocr_rejects_empty_image(gateway_client):
    response = gateway_client.post(
        "/api/ocr",
        files={"file": ("empty.jpg", b"", "image/jpeg")},
    )

    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_gateway_sql_query_execution(gateway_client):
    query_payload = {
        "database": "vehicle_registry.db",
        "query": "SELECT registration_number, make, model FROM vehicle_registry LIMIT 3;"
    }
    resp = gateway_client.post("/api/sql", json=query_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["database"] == "vehicle_registry.db"
    assert "columns" in data
    assert len(data["columns"]) == 3
    assert len(data["rows"]) <= 3


def test_gateway_sql_disallowed_statement(gateway_client):
    # Security test: verify DROP statements are blocked
    query_payload = {
        "database": "vehicle_registry.db",
        "query": "DROP TABLE vehicle_registry;"
    }
    resp = gateway_client.post("/api/sql", json=query_payload)
    assert resp.status_code == 403
