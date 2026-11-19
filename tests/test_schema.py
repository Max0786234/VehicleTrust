"""Phase 3 database tests: 4-6 FK-linked tables per DB, FK enforcement, migrations, CRUD."""
import os
import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

import databases.common as dbcommon
from database_common import get_session_factory
from databases import MODULES, initialize_database
from databases.common import describe_schema, foreign_key_violations, foreign_keys_enabled

EXPECTED_TABLES = {
    "vehicle_registry": {"vehicles", "vehicle_owners", "manufacturers", "vehicle_models", "vehicle_categories"},
    "insurance_records": {"insurance_policies", "insurance_providers", "policy_holders", "coverage_details", "insurance_claims"},
    "registration_authority": {"rto_registrations", "rto_offices", "registration_certificates", "ownership_transfers",
                               "registration_events"},
    "theft_scrapping": {"theft_scrapping_records", "police_stations", "theft_reports", "investigation_details",
                        "recovery_records", "scrapping_records"},
    "audit_log": {"cleansing_audit_log", "reviewers", "audit_sessions", "audit_evidence", "data_change_history"},
}


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(dbcommon, "BACKUP_DIR", str(tmp_path / "backups"))

    def make(key):
        return initialize_database(key, str(tmp_path / f"{key}.db"))
    return make


@pytest.mark.parametrize("key", list(EXPECTED_TABLES))
def test_each_database_has_expected_relational_tables(fresh, key):
    engine = fresh(key)
    schema = describe_schema(engine)
    names = {t["table"] for t in schema["tables"]}
    assert EXPECTED_TABLES[key] <= names
    assert 4 <= len(names) <= 6
    fk_count = sum(len(t["foreign_keys"]) for t in schema["tables"])
    assert fk_count >= 3, "tables must be joined by FK-PK relationships"
    assert foreign_keys_enabled(engine)
    assert foreign_key_violations(engine) == []
    assert all(t["row_count"] > 0 for t in schema["tables"] if t["table"] not in ("data_change_history",))


def test_databases_are_independent_files(fresh, tmp_path):
    for key in EXPECTED_TABLES:
        fresh(key)
    for key, tables in EXPECTED_TABLES.items():
        con = sqlite3.connect(tmp_path / f"{key}.db")
        names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        con.close()
        for other, other_tables in EXPECTED_TABLES.items():
            if other != key:
                assert not (other_tables - {"sqlite_sequence"}) & names


ORPHAN_INSERTS = {
    "vehicle_registry": "INSERT INTO vehicles (registration_number, model_id, colour, registration_date, state) "
                        "VALUES ('ZZ99ZZ9999', 99999, 'Red', '2024-01-01', 'Delhi')",
    "insurance_records": "INSERT INTO coverage_details (policy_id, coverage_type) VALUES (99999, 'X')",
    "registration_authority": "INSERT INTO ownership_transfers (registration_id, office_id, transfer_date, previous_owner, new_owner) "
                              "VALUES (99999, 1, '2024-01-01', 'A', 'B')",
    "theft_scrapping": "INSERT INTO investigation_details (theft_report_id, investigating_officer, investigation_status, last_updated) "
                       "VALUES (99999, 'X', 'OPEN', '2024-01-01')",
    "audit_log": "INSERT INTO audit_evidence (audit_log_id, evidence_source) VALUES (99999, 'x')",
}


@pytest.mark.parametrize("key", list(ORPHAN_INSERTS))
def test_foreign_keys_are_enforced(fresh, key):
    from sqlalchemy import text
    engine = fresh(key)
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(ORPHAN_INSERTS[key]))


def test_restrict_and_cascade_behaviour(fresh):
    from sqlalchemy import text
    reg = fresh("vehicle_registry")
    with pytest.raises(IntegrityError):  # manufacturer still referenced by models -> RESTRICT
        with reg.begin() as conn:
            conn.execute(text("DELETE FROM manufacturers WHERE name='Honda'"))
    ins = fresh("insurance_records")
    with ins.begin() as conn:
        pid = conn.execute(text("SELECT id FROM insurance_policies WHERE policy_number='POL-HDFC-9901'")).scalar()
        assert conn.execute(text("SELECT COUNT(*) FROM insurance_claims WHERE policy_id=:p"), {"p": pid}).scalar() == 1
        conn.execute(text("DELETE FROM insurance_policies WHERE id=:p"), {"p": pid})
        assert conn.execute(text("SELECT COUNT(*) FROM coverage_details WHERE policy_id=:p"), {"p": pid}).scalar() == 0
        assert conn.execute(text("SELECT COUNT(*) FROM insurance_claims WHERE policy_id=:p"), {"p": pid}).scalar() == 0


def _legacy_files(tmp_path):
    """Builds Phase 2 single-table databases (exact legacy DDL) with one user-edited row each."""
    paths = {k: str(tmp_path / f"legacy_{k}.db") for k in EXPECTED_TABLES}
    con = sqlite3.connect(paths["vehicle_registry"])
    con.execute("CREATE TABLE vehicle_registry (id INTEGER PRIMARY KEY AUTOINCREMENT, registration_number VARCHAR(32) NOT NULL UNIQUE, "
                "make VARCHAR(64) NOT NULL, model VARCHAR(64) NOT NULL, colour VARCHAR(32) NOT NULL, vehicle_type VARCHAR(32) NOT NULL, "
                "registration_date VARCHAR(16) NOT NULL, state VARCHAR(32) NOT NULL)")
    con.execute("CREATE INDEX ix_vehicle_registry_id ON vehicle_registry (id)")
    con.executemany("INSERT INTO vehicle_registry VALUES (?,?,?,?,?,?,?,?)", [
        (5, "DL01AB1234", "Honda", "City", "Pearl White", "Sedan", "2020-05-15", "Delhi"),  # user-corrected colour
        (9, "XX11YY2222", "Tesla", "Model 3", "Red", "Electric Sedan", "2024-01-01", "Delhi"),  # user-created row
    ])
    con.commit(); con.close()
    con = sqlite3.connect(paths["insurance_records"])
    con.execute("CREATE TABLE insurance_policies (id INTEGER PRIMARY KEY AUTOINCREMENT, policy_number VARCHAR(64) NOT NULL UNIQUE, "
                "recorded_vehicle_number VARCHAR(32) NOT NULL, insurer VARCHAR(64) NOT NULL, policy_start_date VARCHAR(16) NOT NULL, "
                "expiry_date VARCHAR(16) NOT NULL, policy_status VARCHAR(32) NOT NULL)")
    con.execute("CREATE UNIQUE INDEX ix_insurance_policies_policy_number ON insurance_policies (policy_number)")
    con.execute("INSERT INTO insurance_policies VALUES (7,'POL-USER-1','XX11YY2222','New Insurer Ltd','2024-01-01','2025-01-01','EXPIRED')")
    con.commit(); con.close()
    con = sqlite3.connect(paths["registration_authority"])
    con.execute("CREATE TABLE rto_registrations (id INTEGER PRIMARY KEY AUTOINCREMENT, plate_identifier VARCHAR(32) NOT NULL UNIQUE, "
                "make VARCHAR(64) NOT NULL, model VARCHAR(64) NOT NULL, colour VARCHAR(32) NOT NULL, registration_date VARCHAR(16) NOT NULL, "
                "state VARCHAR(32) NOT NULL, authority_reference VARCHAR(64) NOT NULL)")
    con.execute("INSERT INTO rto_registrations VALUES (3,'XX11YY2222','Tesla','Model 3','Red','2024-01-01','Delhi','RTO-XX-1')")
    con.commit(); con.close()
    con = sqlite3.connect(paths["audit_log"])
    con.execute("CREATE TABLE cleansing_audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, affected_source VARCHAR(64) NOT NULL, "
                "record_id INTEGER NOT NULL, field_name VARCHAR(64) NOT NULL, old_value VARCHAR(255), new_value VARCHAR(255), "
                "reviewer_decision VARCHAR(32) NOT NULL, timestamp DATETIME NOT NULL, reason TEXT)")
    con.execute("INSERT INTO cleansing_audit_log VALUES (4,'vehicle_registry',5,'colour','White','Pearl White','ACCEPTED','2026-01-01 10:00:00','ok')")
    con.commit(); con.close()
    return paths


def test_migration_preserves_existing_records_and_ids(tmp_path, monkeypatch):
    backups = tmp_path / "backups"
    monkeypatch.setattr(dbcommon, "BACKUP_DIR", str(backups))
    paths = _legacy_files(tmp_path)

    reg = initialize_database("vehicle_registry", paths["vehicle_registry"])
    con = sqlite3.connect(paths["vehicle_registry"])
    rows = con.execute("SELECT id, registration_number, make, model, colour, vehicle_type FROM vehicle_registry ORDER BY id").fetchall()
    assert (5, "DL01AB1234", "Honda", "City", "Pearl White", "Sedan") in rows   # edit preserved, id preserved
    assert (9, "XX11YY2222", "Tesla", "Model 3", "Red", "Electric Sedan") in rows
    assert con.execute("SELECT type FROM sqlite_master WHERE name='vehicle_registry'").fetchone()[0] == "view"
    # seed data is NOT merged into a migrated, non-empty database (only related rows are added)
    assert con.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0] == 2
    owner = con.execute("SELECT o.full_name FROM vehicles v JOIN vehicle_owners o ON o.id=v.owner_id WHERE v.id=5").fetchone()
    assert owner == ("Aarav Sharma",)
    con.close()
    assert foreign_key_violations(reg) == []

    initialize_database("insurance_records", paths["insurance_records"])
    con = sqlite3.connect(paths["insurance_records"])
    assert con.execute("SELECT p.id, pr.name FROM insurance_policies p JOIN insurance_providers pr ON pr.id=p.provider_id").fetchall() \
        == [(7, "New Insurer Ltd")]
    assert con.execute("SELECT name FROM sqlite_master WHERE name LIKE '_legacy%'").fetchall() == []
    con.close()

    initialize_database("registration_authority", paths["registration_authority"])
    con = sqlite3.connect(paths["registration_authority"])
    assert con.execute("SELECT r.id, o.office_code FROM rto_registrations r JOIN rto_offices o ON o.id=r.office_id").fetchall() \
        == [(3, "XX11")]
    con.close()

    initialize_database("audit_log", paths["audit_log"])
    con = sqlite3.connect(paths["audit_log"])
    assert con.execute("SELECT id, new_value, reviewer_id FROM cleansing_audit_log WHERE id=4").fetchone() == (4, "Pearl White", None)
    con.close()

    backed_up = sorted(os.listdir(backups))
    assert len(backed_up) == 4 and all("pre_phase3_migration" in b for b in backed_up)


def test_initialization_is_idempotent(fresh, tmp_path):
    for key in EXPECTED_TABLES:
        fresh(key)
    before = {k: {t["table"]: t["row_count"] for t in describe_schema(initialize_database(k, str(tmp_path / f"{k}.db")))["tables"]}
              for k in EXPECTED_TABLES}
    after = {k: {t["table"]: t["row_count"] for t in describe_schema(initialize_database(k, str(tmp_path / f"{k}.db")))["tables"]}
             for k in EXPECTED_TABLES}
    assert before == after


def test_registry_crud_through_normalized_tables():
    from service_registry import app
    client = TestClient(app)
    created = client.post("/records", json={"registration_number": "MH 47 ZZ 0001", "make": "Ather", "model": "450X",
                                            "colour": "Grey", "vehicle_type": "Electric Scooter",
                                            "registration_date": "2025-01-01", "state": "Maharashtra",
                                            "owner_name": "Test Owner"})
    assert created.status_code == 201, created.text
    rec = created.json()
    assert rec["registration_number"] == "MH47ZZ0001" and rec["make"] == "Ather" and rec["owner_name"] == "Test Owner"
    updated = client.put(f"/records/{rec['id']}", json={"make": "TVS", "model": "iQube"}).json()
    assert (updated["make"], updated["model"], updated["vehicle_type"]) == ("TVS", "iQube", "Electric Scooter")
    assert updated["model_id"] != rec["model_id"]
    bad = client.put(f"/records/{rec['id']}", json={"owner_id": 999999})
    assert bad.status_code == 400 and "FK owner_id" in bad.json()["detail"]
    assert client.delete(f"/records/{rec['id']}").status_code == 200
    assert client.get(f"/records/{rec['id']}").status_code == 404


def test_service_schema_tables_and_integrity_endpoints():
    from service_theft import app
    client = TestClient(app)
    schema = client.get("/schema").json()
    fks = {(t["table"], fk["column"], fk["references_table"]) for t in schema["tables"] for fk in t["foreign_keys"]}
    assert ("theft_reports", "station_id", "police_stations") in fks
    assert ("recovery_records", "theft_report_id", "theft_reports") in fks
    assert client.get("/integrity").json() == {"service": "theft_scrapping", "foreign_keys_enabled": True,
                                               "violations": [], "ok": True}
    rows = client.get("/tables/police_stations", params={"limit": 3}).json()
    assert len(rows["rows"]) == 3 and "station_code" in rows["columns"]
    assert client.get("/tables/not_a_table").status_code == 404
    health = client.get("/health").json()
    assert health["table_count"] == 6 and health["machine"] == "machine-1"


def test_local_federated_query_discovers_fk_context():
    from service_registration import app
    client = TestClient(app)
    res = client.post("/federated/query", json={"plate": "UP16BT9900", "include": ["office", "transfers", "certificates"]}).json()
    assert res["match_count"] == 1
    m = res["matches"][0]
    assert m["related"]["office"]["office_code"] == "UP16"
    assert m["related"]["transfers"][0]["new_owner"] == "Suresh Yadav"
    assert "events" not in m["related"]  # relations not requested are not traversed
    relations = {p["relation"] for p in m["relationship_paths"]}
    assert {"office", "transfers", "transfer_office", "certificates"} <= relations
    assert set(res["tables_touched"]) >= {"rto_registrations", "rto_offices", "ownership_transfers", "registration_certificates"}


def test_audit_entry_creates_evidence_and_change_history():
    from service_audit import app
    client = TestClient(app)
    entry = client.post("/records", json={
        "affected_source": "vehicle_registry", "record_id": 3, "field_name": "colour", "old_value": "Crimson Red",
        "new_value": "Fire Red", "reviewer_decision": "ACCEPTED", "reason": "test", "vehicle_plate": "KA05MJ5555",
        "reviewer": "a.verma", "evidence": {"source": "registration_authority", "record_id": 3, "field": "colour",
                                            "value": "Fire Red", "plate_similarity": 1.0}}).json()
    assert entry["reviewer"] == "a.verma" and entry["vehicle_plate"] == "KA05MJ5555"
    res = client.post("/federated/query", json={"plate": "KA05MJ5555", "record_refs": []}).json()
    mine = next(m for m in res["matches"] if m["record_id"] == entry["id"])
    assert mine["related"]["evidence"][0]["evidence_value"] == "Fire Red"
    assert mine["related"]["changes"][0]["value_after"] == "Fire Red"
    assert mine["related"]["reviewer"]["username"] == "a.verma"
    assert client.put(f"/records/{entry['id']}", json={}).status_code == 405  # append-only
