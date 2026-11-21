import os
import sys
import tempfile

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Tests never touch the real database files: every service is pointed at a fresh
# temporary copy BEFORE any service module is imported (services bind their DB at import).
TEST_DB_DIR = tempfile.mkdtemp(prefix="vehicletrust_test_dbs_")
for _env, _name in [
    ("REGISTRY_DB_FILE", "vehicle_registry.db"),
    ("INSURANCE_DB_FILE", "insurance_records.db"),
    ("REGISTRATION_DB_FILE", "registration_authority.db"),
    ("THEFT_DB_FILE", "theft_scrapping.db"),
    ("AUDIT_DB_FILE", "audit_log.db"),
]:
    os.environ[_env] = os.path.join(TEST_DB_DIR, _name)
# Ensure URL configuration is deterministic regardless of the developer's .env
os.environ["VEHICLETRUST_KEEP_ENV"] = "1"  # do not let .env override the values set here
os.environ["LLM_UNDERSTANDING"] = "off"    # tests are deterministic; LLM tests mock Ollama explicitly
for _env in ["REGISTRY_API_URL", "INSURANCE_API_URL", "REGISTRATION_API_URL", "THEFT_API_URL", "AUDIT_API_URL",
             "MACHINE1_HOST", "MACHINE2_HOST"]:
    os.environ[_env] = ""
