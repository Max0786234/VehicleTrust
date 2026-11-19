import datetime
import os
import pytest
from database_common import log_cleansing_action, get_audit_logs
from integration import (
    SchemaMapper,
    CanonicalVehicleRecord,
    evaluate_insurance_risk,
    generate_cleansing_proposals,
    parse_iso_date,
    apply_cleansing_decision,
    get_cleansing_audit_logs,
)


def test_schema_mapper():
    raw_reg = {
        "id": 10,
        "registration_number": "DL 01 AB 1234",
        "make": "Honda",
        "model": "City",
        "colour": "White",
        "vehicle_type": "Sedan",
        "registration_date": "2020-05-15",
        "state": "Delhi",
    }
    canon = SchemaMapper.to_canonical("vehicle_registry", raw_reg)
    assert canon["normalized_plate"] == "DL01AB1234"
    assert canon["source_system"] == "vehicle_registry"
    assert canon["make"] == "Honda"

    raw_ins = {
        "id": 5,
        "policy_number": "POL-99",
        "recorded_vehicle_number": "DL-01-AB-1234",
        "insurer": "ICICI",
        "policy_start_date": "2026-01-01",
        "expiry_date": "2027-01-01",
        "policy_status": "ACTIVE",
    }
    canon_ins = SchemaMapper.to_canonical("insurance_records", raw_ins)
    assert canon_ins["normalized_plate"] == "DL01AB1234"
    assert canon_ins["policy_number"] == "POL-99"


def test_canonical_record_conflict_detection():
    canon = CanonicalVehicleRecord("DL01AB1234")
    canon.add_source_record(
        "vehicle_registry",
        {"id": 1, "registration_number": "DL01AB1234", "make": "Honda", "model": "City", "colour": "White", "state": "Delhi"},
        1.0,
        "HIGH",
    )
    canon.add_source_record(
        "registration_authority",
        {"id": 1, "plate_identifier": "DL01AB1234", "make": "Honda", "model": "City ZX", "colour": "Pearl White", "state": "Delhi"},
        1.0,
        "HIGH",
    )
    canon.detect_conflicts()
    assert len(canon.conflicts) == 2
    fields = [c["field"] for c in canon.conflicts]
    assert "model" in fields
    assert "colour" in fields


def test_insurance_rules_current():
    eval_date = datetime.date(2026, 10, 21)
    policies = [{
        "raw_record": {
            "policy_number": "POL-1",
            "policy_start_date": "2026-01-01",
            "expiry_date": "2027-01-01",
            "policy_status": "ACTIVE",
            "insurer": "HDFC ERGO",
        }
    }]
    risk = evaluate_insurance_risk(policies, evaluation_date=eval_date)
    assert risk["status"] == "CURRENT"
    assert risk["risk_level"] == "CLEAR"


def test_insurance_rules_expired():
    eval_date = datetime.date(2026, 10, 21)
    policies = [{
        "raw_record": {
            "policy_number": "POL-2",
            "policy_start_date": "2024-01-01",
            "expiry_date": "2025-01-01",
            "policy_status": "EXPIRED",
            "insurer": "ICICI Lombard",
        }
    }]
    risk = evaluate_insurance_risk(policies, evaluation_date=eval_date)
    assert risk["status"] == "EXPIRED"
    assert risk["risk_level"] == "HIGH_RISK"
    assert "challan" in risk["recommended_action"].lower()


def test_insurance_rules_future_policy():
    eval_date = datetime.date(2026, 10, 21)
    policies = [{
        "raw_record": {
            "policy_number": "POL-3",
            "policy_start_date": "2027-01-01",
            "expiry_date": "2028-01-01",
            "policy_status": "ACTIVE",
            "insurer": "Bajaj Allianz",
        }
    }]
    risk = evaluate_insurance_risk(policies, evaluation_date=eval_date)
    assert risk["status"] == "FUTURE_POLICY"
    assert risk["risk_level"] == "WARNING"


def test_insurance_rules_conflicting():
    eval_date = datetime.date(2026, 10, 21)
    policies = [
        {
            "raw_record": {
                "policy_number": "POL-4A",
                "policy_start_date": "2026-01-01",
                "expiry_date": "2027-01-01",
                "policy_status": "ACTIVE",
                "insurer": "HDFC ERGO",
            }
        },
        {
            "raw_record": {
                "policy_number": "POL-4B",
                "policy_start_date": "2026-02-01",
                "expiry_date": "2027-02-01",
                "policy_status": "ACTIVE",
                "insurer": "Reliance General",
            }
        },
    ]
    risk = evaluate_insurance_risk(policies, evaluation_date=eval_date)
    assert risk["status"] == "CONFLICTING"


def test_insurance_rules_not_found():
    eval_date = datetime.date(2026, 10, 21)
    risk = evaluate_insurance_risk([], evaluation_date=eval_date)
    assert risk["status"] == "NOT_FOUND"


def test_insurance_rules_unverified_offline():
    eval_date = datetime.date(2026, 10, 21)
    risk = evaluate_insurance_risk([], evaluation_date=eval_date, insurance_service_available=False)
    assert risk["status"] == "UNVERIFIED"
    assert "offline" in risk["status_label"].lower()


def test_insurance_rules_unverified_low_confidence():
    eval_date = datetime.date(2026, 10, 21)
    risk = evaluate_insurance_risk([], evaluation_date=eval_date, plate_confidence="LOW")
    assert risk["status"] == "UNVERIFIED"


def test_generate_cleansing_proposals():
    canon = CanonicalVehicleRecord("DL01AB1234")
    canon.add_source_record(
        "vehicle_registry",
        {"id": 4, "registration_number": "DL01AB1234", "make": "Honda", "model": "City", "colour": "White", "state": "Delhi"},
        1.0,
        "HIGH",
    )
    canon.add_source_record(
        "registration_authority",
        {"id": 4, "plate_identifier": "DL01AB1234", "make": "Honda", "model": "City", "colour": "Pearl White", "state": "Delhi"},
        1.0,
        "HIGH",
    )
    proposals = generate_cleansing_proposals(canon.to_dict())
    assert len(proposals) == 1
    assert proposals[0]["field_name"] == "colour"
    assert proposals[0]["current_value"] == "White"
    assert proposals[0]["proposed_value"] == "Pearl White"
    assert proposals[0]["source_record_id"] == 4
    assert proposals[0]["source_plate"] == "DL01AB1234"


def test_generate_cleansing_proposals_includes_plate_and_missing_values():
    canon = CanonicalVehicleRecord("DLO1AB1234")
    canon.add_source_record(
        "vehicle_registry",
        {"id": 4, "registration_number": "DLO1AB1234", "make": None, "model": "City", "colour": "White", "state": "Delhi"},
        0.9,
        "HIGH",
    )
    canon.add_source_record(
        "registration_authority",
        {"id": 9, "plate_identifier": "DL01AB1234", "make": "Honda", "model": "City", "colour": "White", "state": "Delhi"},
        0.9,
        "HIGH",
    )

    proposals = generate_cleansing_proposals(canon.to_dict())

    assert {(p["field_name"], p["current_value"], p["proposed_value"]) for p in proposals} == {
        ("registration_number", "DLO1AB1234", "DL01AB1234"),
        ("make", None, "Honda"),
    }


def test_generate_cleansing_proposals_rejects_unrelated_authority_record():
    canon = CanonicalVehicleRecord("DL01AB1234")
    canon.add_source_record(
        "vehicle_registry",
        {"id": 4, "registration_number": "DL01AB1234", "make": "Honda"},
        1.0,
        "HIGH",
    )
    canon.add_source_record(
        "registration_authority",
        {"id": 9, "plate_identifier": "KA05MJ5555", "make": "Tata"},
        0.1,
        "LOW",
    )

    assert generate_cleansing_proposals(canon.to_dict()) == []


def test_apply_cleansing_decision_verifies_evidence_updates_and_audits(monkeypatch):
    import integration

    registry = {
        "id": 4,
        "registration_number": "DL01AB1234",
        "colour": "White",
    }
    authority = {
        "id": 9,
        "plate_identifier": "DL01AB1234",
        "colour": "Pearl White",
    }
    audits = []

    class Response:
        status_code = 200
        text = ""

        def __init__(self, body):
            self.body = body

        def json(self):
            return self.body

    class Client:
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            return Response(registry if "8101" in url else authority)

        def put(self, url, json):
            registry.update(json)
            return Response(registry)

    monkeypatch.setattr(integration.httpx, "Client", Client)
    monkeypatch.setattr(integration, "log_cleansing_action", lambda **kwargs: audits.append(kwargs))
    proposal = {
        "target_source": "vehicle_registry",
        "record_id": 4,
        "field_name": "colour",
        "current_value": "White",
        "proposed_value": "Pearl White",
        "proposed_by": "registration_authority",
        "source_record_id": 9,
        "source_plate": "DL01AB1234",
        "registry_plate": "DL01AB1234",
    }

    ok, message = apply_cleansing_decision(
        proposal,
        "ACCEPTED",
        "Confirmed from vehicle image and RTO record",
        {"vehicle_registry": "http://registry:8101", "registration_authority": "http://authority:8103"},
    )

    assert ok
    assert "Successfully updated colour" in message
    assert registry["colour"] == "Pearl White"
    assert audits[0]["reviewer_decision"] == "ACCEPTED"
    assert audits[0]["new_value"] == "Pearl White"


def test_apply_cleansing_decision_rejects_stale_proposal(monkeypatch):
    import integration

    audits = []

    class Response:
        status_code = 200
        text = ""

        def __init__(self, body):
            self.body = body

        def json(self):
            return self.body

    class Client:
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            if "8101" in url:
                return Response({"id": 4, "registration_number": "DL01AB1234", "colour": "Blue"})
            return Response({"id": 9, "plate_identifier": "DL01AB1234", "colour": "Pearl White"})

        def put(self, url, json):
            raise AssertionError("Stale proposals must not update records")

    monkeypatch.setattr(integration.httpx, "Client", Client)
    monkeypatch.setattr(integration, "log_cleansing_action", lambda **kwargs: audits.append(kwargs))
    proposal = {
        "target_source": "vehicle_registry",
        "record_id": 4,
        "field_name": "colour",
        "current_value": "White",
        "proposed_value": "Pearl White",
        "proposed_by": "registration_authority",
        "source_record_id": 9,
        "source_plate": "DL01AB1234",
        "registry_plate": "DL01AB1234",
    }

    ok, message = apply_cleansing_decision(
        proposal,
        "ACCEPTED",
        "",
        {"vehicle_registry": "http://registry:8101", "registration_authority": "http://authority:8103"},
    )

    assert not ok
    assert "changed after this proposal" in message
    assert audits[0]["reviewer_decision"] == "STALE"


def test_apply_cleansing_decision_audits_failed_update_as_failed(monkeypatch):
    import integration

    audits = []

    class Response:
        text = "service unavailable"

        def __init__(self, status_code, body=None):
            self.status_code = status_code
            self.body = body or {}

        def json(self):
            return self.body

    class Client:
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            if "8101" in url:
                return Response(200, {"id": 4, "registration_number": "DL01AB1234", "colour": "White"})
            return Response(200, {"id": 9, "plate_identifier": "DL01AB1234", "colour": "Pearl White"})

        def put(self, url, json):
            return Response(503)

    monkeypatch.setattr(integration.httpx, "Client", Client)
    monkeypatch.setattr(integration, "log_cleansing_action", lambda **kwargs: audits.append(kwargs))
    proposal = {
        "target_source": "vehicle_registry",
        "record_id": 4,
        "field_name": "colour",
        "current_value": "White",
        "proposed_value": "Pearl White",
        "proposed_by": "registration_authority",
        "source_record_id": 9,
        "source_plate": "DL01AB1234",
        "registry_plate": "DL01AB1234",
    }

    ok, message = apply_cleansing_decision(
        proposal,
        "ACCEPTED",
        "",
        {"vehicle_registry": "http://registry:8101", "registration_authority": "http://authority:8103"},
    )

    assert not ok
    assert "HTTP 503" in message
    assert audits[0]["reviewer_decision"] == "FAILED"
    assert audits[0]["new_value"] is None


def test_audit_logging(tmp_path):
    test_db = str(tmp_path / "test_audit.db")
    entry = log_cleansing_action(
        affected_source="vehicle_registry",
        record_id=1,
        field_name="colour",
        old_value="White",
        new_value="Pearl White",
        reviewer_decision="ACCEPTED",
        reason="Updated to match official RTO record",
        db_path=test_db,
    )
    assert entry["id"] == 1
    assert entry["reviewer_decision"] == "ACCEPTED"

    logs = get_audit_logs(limit=10, db_path=test_db)
    assert len(logs) == 1
    assert logs[0]["field_name"] == "colour"


def test_remote_audit_service_read_and_write(monkeypatch):
    import integration

    calls = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_post(url, json, timeout):
        calls.append(("POST", url, json))
        return Response({"id": 1, **json})

    def fake_get(url, params, timeout):
        calls.append(("GET", url, params))
        return Response([{"id": 1, "field_name": "colour"}])

    monkeypatch.setattr(integration.httpx, "post", fake_post)
    monkeypatch.setattr(integration.httpx, "get", fake_get)

    integration._write_cleansing_audit(
        {"audit_log": "http://127.0.0.1:8105/"},
        {
            "affected_source": "vehicle_registry",
            "record_id": 4,
            "field_name": "colour",
            "old_value": "White",
            "new_value": "Pearl White",
            "reviewer_decision": "ACCEPTED",
            "reason": "Verified",
        },
    )
    logs = get_cleansing_audit_logs(10, "vehicle_registry", "http://127.0.0.1:8105/")

    assert calls[0][0:2] == ("POST", "http://127.0.0.1:8105/records")
    assert calls[1] == (
        "GET",
        "http://127.0.0.1:8105/records",
        {"limit": 10, "source": "vehicle_registry"},
    )
    assert logs[0]["field_name"] == "colour"
