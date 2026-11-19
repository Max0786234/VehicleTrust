"""Central service topology and environment configuration for VehicleTrust.

Every component (services, gateway, Streamlit, launcher) reads service locations
from here so that the two-laptop split is configured in exactly one place (.env).

URL resolution order for each service:
  1. Explicit URL variable, e.g. REGISTRY_API_URL=http://192.168.1.50:8101
  2. Host variable of the machine that owns the service (MACHINE2_HOST / MACHINE1_HOST)
  3. http://127.0.0.1:<port>  (single-laptop development)
"""
import os
from typing import Dict, List

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# .env is authoritative: a terminal may still carry stale values (e.g. an IDE that injected an older
# .env into the shell when it opened). Tests/simulations set VEHICLETRUST_KEEP_ENV=1 to keep their own.
load_dotenv(os.path.join(BASE_DIR, ".env"), override=os.getenv("VEHICLETRUST_KEEP_ENV") != "1")

# key -> service specification. `machine` is the owner in the 2+3 deployment.
SERVICES: Dict[str, Dict] = {
    "vehicle_registry": {
        "node": "registry", "module": "service_registry", "label": "Vehicle Registry",
        "default_port": 8101, "port_env": "REGISTRY_PORT", "url_env": "REGISTRY_API_URL",
        "db_env": "REGISTRY_DB_FILE", "db_default": "vehicle_registry.db", "machine": "machine-2",
    },
    "insurance_records": {
        "node": "insurance", "module": "service_insurance", "label": "Insurance Records",
        "default_port": 8102, "port_env": "INSURANCE_PORT", "url_env": "INSURANCE_API_URL",
        "db_env": "INSURANCE_DB_FILE", "db_default": "insurance_records.db", "machine": "machine-2",
    },
    "registration_authority": {
        "node": "registration", "module": "service_registration", "label": "Registration Authority",
        "default_port": 8103, "port_env": "REGISTRATION_PORT", "url_env": "REGISTRATION_API_URL",
        "db_env": "REGISTRATION_DB_FILE", "db_default": "registration_authority.db", "machine": "machine-2",
    },
    "theft_scrapping": {
        "node": "theft", "module": "service_theft", "label": "Theft & Scrapping",
        "default_port": 8104, "port_env": "THEFT_PORT", "url_env": "THEFT_API_URL",
        "db_env": "THEFT_DB_FILE", "db_default": "theft_scrapping.db", "machine": "machine-1",
    },
    "audit_log": {
        "node": "audit", "module": "service_audit", "label": "Cleansing Audit Log",
        "default_port": 8105, "port_env": "AUDIT_PORT", "url_env": "AUDIT_API_URL",
        "db_env": "AUDIT_DB_FILE", "db_default": "audit_log.db", "machine": "machine-1",
    },
}

NODE_TO_KEY = {spec["node"]: key for key, spec in SERVICES.items()}

# The four vehicle-domain data services (audit is handled separately in Phase 2 code).
DATA_SERVICE_KEYS: List[str] = ["vehicle_registry", "insurance_records", "registration_authority", "theft_scrapping"]
ALL_SERVICE_KEYS: List[str] = DATA_SERVICE_KEYS + ["audit_log"]

MACHINE_GROUPS: Dict[str, List[str]] = {
    "machine-1": ["theft", "audit"],                      # + gateway (8000) + Streamlit (8501)
    "machine-2": ["registry", "insurance", "registration"],
    "all": ["registry", "insurance", "registration", "theft", "audit"],  # single-laptop development
}
GROUPS_WITH_FRONTEND = {"machine-1", "all"}

GATEWAY_PORT = int(os.getenv("GATEWAY_PORT", "8000"))
STREAMLIT_PORT = int(os.getenv("STREAMLIT_PORT", "8501"))
FEDERATION_TIMEOUT = float(os.getenv("FEDERATION_TIMEOUT", "4.0"))
DOCUMENTS_DIR = os.getenv("DOCUMENTS_DIR", os.path.join(BASE_DIR, "documents"))


def service_port(key: str) -> int:
    spec = SERVICES[key]
    return int(os.getenv(spec["port_env"], str(spec["default_port"])))


def service_url(key: str) -> str:
    spec = SERVICES[key]
    explicit = os.getenv(spec["url_env"], "").strip()
    if explicit:
        return explicit.rstrip("/")
    host_var = "MACHINE2_HOST" if spec["machine"] == "machine-2" else "MACHINE1_HOST"
    host = os.getenv(host_var, "").strip() or "127.0.0.1"
    return f"http://{host}:{service_port(key)}"


def service_urls() -> Dict[str, str]:
    return {key: service_url(key) for key in ALL_SERVICE_KEYS}


def db_path(key: str) -> str:
    spec = SERVICES[key]
    path = os.getenv(spec["db_env"], spec["db_default"])
    return path if os.path.isabs(path) else os.path.join(BASE_DIR, path)


def gateway_url() -> str:
    return os.getenv("GATEWAY_URL", f"http://127.0.0.1:{GATEWAY_PORT}").rstrip("/")
