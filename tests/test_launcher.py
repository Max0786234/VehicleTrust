"""Deployment configuration and launcher tests (no processes started)."""
import os

import config
import start_node


def test_machine_groups_are_the_required_2_plus_3_split():
    assert config.MACHINE_GROUPS["machine-1"] == ["theft", "audit"]
    assert config.MACHINE_GROUPS["machine-2"] == ["registry", "insurance", "registration"]
    assert "machine-1" in config.GROUPS_WITH_FRONTEND and "machine-2" not in config.GROUPS_WITH_FRONTEND
    owners = {spec["node"]: spec["machine"] for spec in config.SERVICES.values()}
    assert owners == {"registry": "machine-2", "insurance": "machine-2", "registration": "machine-2",
                      "theft": "machine-1", "audit": "machine-1"}


def test_service_url_resolution_order(monkeypatch):
    monkeypatch.setenv("REGISTRY_API_URL", "")
    monkeypatch.setenv("MACHINE2_HOST", "")
    assert config.service_url("vehicle_registry") == "http://127.0.0.1:8101"
    monkeypatch.setenv("MACHINE2_HOST", "10.0.0.7")
    assert config.service_url("vehicle_registry") == "http://10.0.0.7:8101"
    assert config.service_url("theft_scrapping") == "http://127.0.0.1:8104"  # machine-1 service stays local
    monkeypatch.setenv("REGISTRY_API_URL", "http://192.168.1.50:8101/")
    assert config.service_url("vehicle_registry") == "http://192.168.1.50:8101"  # explicit URL wins
    monkeypatch.setenv("INSURANCE_PORT", "18102")
    assert config.service_url("insurance_records") == "http://10.0.0.7:18102"


def test_generated_env_for_each_machine():
    m1 = start_node.env_text("machine-1", "192.168.1.50")
    for line in ["REGISTRY_API_URL=http://192.168.1.50:8101", "INSURANCE_API_URL=http://192.168.1.50:8102",
                 "REGISTRATION_API_URL=http://192.168.1.50:8103", "THEFT_API_URL=http://127.0.0.1:8104",
                 "AUDIT_API_URL=http://127.0.0.1:8105"]:
        assert line in m1
    assert "LAPTOP2_IP" in start_node.env_text("machine-1")  # placeholder, never a hard-coded IP
    assert "API_URL" not in start_node.env_text("machine-2")


def test_package_contains_code_but_only_the_machines_own_databases(tmp_path):
    from databases import initialize_database
    for key in config.ALL_SERVICE_KEYS:  # make sure all five (test) DB files exist before packaging
        initialize_database(key)
    dest =start_node.package("machine-2", str(tmp_path), with_data=True, machine2_ip="")
    files = {os.path.relpath(os.path.join(d, f), dest).replace("\\", "/") for d, _, fs in os.walk(dest) for f in fs}
    dbs = {f for f in files if f.endswith(".db")}
    assert dbs == {"vehicle_registry.db", "insurance_records.db", "registration_authority.db"}
    for needed in ["start_node.py", "config.py", "gateway.py", "databases/registry.py", "seed_data.py",
                   "requirements.txt", ".env", "DEPLOYMENT_ROLE.txt", "documents/theft_complaints/DOC-FIR-001.txt"]:
        assert needed in files
    assert not any(f.startswith(("backups/", "linux_venv/", "dist/")) or "__pycache__" in f for f in files)
    assert os.path.exists(dest + ".zip")
    dest1 = start_node.package("machine-1", str(tmp_path), with_data=False, machine2_ip="10.1.1.2")
    assert not [f for _, _, fs in os.walk(dest1) for f in fs if f.endswith(".db")]
    assert "REGISTRY_API_URL=http://10.1.1.2:8101" in open(os.path.join(dest1, ".env"), encoding="utf-8").read()


def test_port_check_detects_busy_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    try:
        assert start_node.port_free(s.getsockname()[1], "127.0.0.1") is False
    finally:
        s.close()
