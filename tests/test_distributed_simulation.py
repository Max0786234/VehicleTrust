"""LOCAL SIMULATION of the two-laptop 2+3 deployment (real processes, real HTTP).

Two clean deployment copies are produced with `start_node.py package`, each started from
its own folder with its own SQLite files:
  "laptop 2" copy: start_node.py machine-2           -> registry / insurance / registration
  "laptop 1" copy: start_node.py machine-1 --no-ui   -> theft / audit, plus the gateway
Alternate ports (181xx) avoid clashing with a running development instance. Machine-2 URLs
use this computer's LAN IP when it is reachable (falls back to 127.0.0.1).
This is a single-computer simulation; it does not replace a test on two physical laptops.
"""
import os
import subprocess
import sys
import time

import httpx
import pytest

import start_node

PORTS = {"REGISTRY_PORT": 18101, "INSURANCE_PORT": 18102, "REGISTRATION_PORT": 18103, "THEFT_PORT": 18104,
         "AUDIT_PORT": 18105}
GATEWAY = 18000


def _kill_tree(proc):
    if proc and proc.poll() is None:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True) if os.name == "nt" \
            else proc.kill()
        proc.wait(timeout=10)


def _wait(url, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=1.0).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    root = tmp_path_factory.mktemp("two_laptops")
    m1 = start_node.package("machine-1", str(root / "laptop1"), with_data=False, machine2_ip="")
    m2 = start_node.package("machine-2", str(root / "laptop2"), with_data=False, machine2_ip="")
    env = {k: v for k, v in os.environ.items() if not k.endswith("_DB_FILE")}  # use each copy's own files
    env.update({k: str(v) for k, v in PORTS.items()}, PYTHONIOENCODING="utf-8")
    procs = {}
    try:
        procs["laptop2"] = subprocess.Popen([sys.executable, "start_node.py", "machine-2", "--skip-checks"], cwd=m2, env=env,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for p in (18101, 18102, 18103):
            assert _wait(f"http://127.0.0.1:{p}/health"), f"laptop-2 service on {p} did not start"
        host = next((ip for ip in start_node.lan_addresses() if _wait(f"http://{ip}:18101/health", 3)), "127.0.0.1")
        env1 = dict(env, REGISTRY_API_URL=f"http://{host}:18101", INSURANCE_API_URL=f"http://{host}:18102",
                    REGISTRATION_API_URL=f"http://{host}:18103", THEFT_API_URL="http://127.0.0.1:18104",
                    AUDIT_API_URL="http://127.0.0.1:18105")
        procs["laptop1"] = subprocess.Popen([sys.executable, "start_node.py", "machine-1", "--no-ui", "--skip-checks"], cwd=m1,
                                            env=env1, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs["gateway"] = subprocess.Popen([sys.executable, "-m", "uvicorn", "gateway:app", "--host", "127.0.0.1", "--port",
                                             str(GATEWAY), "--log-level", "warning"], cwd=m1, env=env1,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for p in (18104, 18105):
            assert _wait(f"http://127.0.0.1:{p}/health"), f"laptop-1 service on {p} did not start"
        assert _wait(f"http://127.0.0.1:{GATEWAY}/api/topology")
        yield {"m1": m1, "m2": m2, "host": host, "procs": procs}
    finally:
        for p in procs.values():
            _kill_tree(p)


def _dbs(folder):
    return sorted(f for f in os.listdir(folder) if f.endswith(".db"))


def test_each_laptop_owns_only_its_databases(cluster):
    assert _dbs(cluster["m2"]) == ["insurance_records.db", "registration_authority.db", "vehicle_registry.db"]
    assert _dbs(cluster["m1"]) == ["audit_log.db", "theft_scrapping.db"]


def test_gateway_status_and_topology(cluster):
    status = httpx.get(f"http://127.0.0.1:{GATEWAY}/api/status", timeout=15).json()["services"]
    assert all(v["online"] for v in status.values()), status
    assert status["vehicle_registry"]["url"] == f"http://{cluster['host']}:18101"
    assert status["vehicle_registry"]["machine"] == "machine-2" and status["theft_scrapping"]["machine"] == "machine-1"


def test_complete_federated_query_across_laptops(cluster):
    r = httpx.post(f"http://127.0.0.1:{GATEWAY}/api/federated-query",
                   json={"query": "Check the complete history of vehicle DLO1AB1234"}, timeout=30).json()
    avail = {k: v["status"] for k, v in r["context"]["service_availability"].items()}
    assert avail == {"vehicle_registry": "ok", "insurance_records": "ok", "registration_authority": "ok",
                     "theft_scrapping": "ok", "audit_log": "ok"}
    assert r["context"]["resolved_entity"]["registration_number"] == "DL01AB1234"
    assert any(c["url"].startswith(f"http://{cluster['host']}:1810") for c in r["context"]["subqueries"])
    assert r["documents"]["documents"], "documents are retrieved on laptop 1"


def test_cleansing_decision_updates_laptop2_and_audits_on_laptop1(cluster):
    g = f"http://127.0.0.1:{GATEWAY}"
    proposals = httpx.post(f"{g}/api/search", json={"query_plate": "KA05MJ5555"}, timeout=15).json()["cleansing_proposals"]
    colour = next(p for p in proposals if p["field_name"] == "colour")
    out = httpx.post(f"{g}/api/cleansing/decide", json={"proposal": colour, "decision": "ACCEPTED",
                                                       "reason": "simulation test"}, timeout=15).json()
    assert out["success"], out
    rec = httpx.get(f"http://{cluster['host']}:18101/records/{colour['record_id']}", timeout=5).json()
    assert rec["colour"] == "Fire Red"
    audit = httpx.post("http://127.0.0.1:18105/federated/query", json={"plate": "KA05MJ5555"}, timeout=5).json()
    accepted = next(m for m in audit["matches"] if m["record"]["reviewer_decision"] == "ACCEPTED")
    assert accepted["related"]["evidence"][0]["evidence_source"] == "registration_authority"
    assert accepted["related"]["changes"][0]["value_before"] == "Crimson Red"


def test_partial_failure_when_laptop2_goes_offline(cluster):
    _kill_tree(cluster["procs"]["laptop2"])
    time.sleep(1)
    r = httpx.post(f"http://127.0.0.1:{GATEWAY}/api/federated-query",
                   json={"query": "Is this vehicle insured, stolen or scrapped? GJ01AB7777", "timeout": 2}, timeout=30).json()
    avail = {k: v["status"] for k, v in r["context"]["service_availability"].items()}
    assert avail["theft_scrapping"] == "ok"
    assert avail["vehicle_registry"] in ("unavailable", "timeout") and avail["insurance_records"] in ("unavailable", "timeout")
    assert r["integration"]["insurance_risk"]["status"] == "UNVERIFIED"
    assert "REPORTED STOLEN" in r["answer"]["headline"]  # laptop-1 data still answers
    assert any("Insurance Records" in m["item"] for m in r["missing_information"])
