"""Gateway API and static server for remote vehicle source databases."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).parent
HOST = os.getenv("GATEWAY_HOST", "0.0.0.0")
PORT = 8000
AUDIT_FILE = ROOT / "audit_log.jsonl"
AUDIT_LOCK = threading.RLock()
SOURCE_TABLES = {"capture": "road_capture", "insurance": "insurance_policy", "registry": "vehicle_registration", "cases": "theft_scrap_case", "ministry": "ministry_report"}
DEFAULT_PORTS = {"capture": 8101, "insurance": 8102, "registry": 8103, "cases": 8104, "ministry": 8105}
SOURCE_URLS = {alias: os.getenv(f"{alias.upper()}_URL", f"http://127.0.0.1:{port}").rstrip("/") for alias, port in DEFAULT_PORTS.items()}


def audit_read() -> list[dict]:
    if not AUDIT_FILE.exists():
        return []
    records = []
    with AUDIT_LOCK, AUDIT_FILE.open(encoding="utf-8") as file:
        for line in file:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def audit_append(record: dict) -> None:
    record = {"id": uuid.uuid4().hex, "timestamp": datetime.now(timezone.utc).isoformat(), **record}
    with AUDIT_LOCK, AUDIT_FILE.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record) + "\n")


def audit_update(record_id: str, **updates: object) -> bool:
    with AUDIT_LOCK:
        records = audit_read()
        changed = False
        for record in records:
            if record.get("id") == record_id:
                record.update(updates)
                changed = True
        if changed:
            with AUDIT_FILE.open("w", encoding="utf-8") as file:
                file.writelines(json.dumps(record) + "\n" for record in records)
        return changed

JOIN_QUERY = """
WITH latest_capture AS (
    SELECT c.*, ROW_NUMBER() OVER (PARTITION BY REPLACE(REPLACE(UPPER(c.plate_text), '-', ''), ' ', '') ORDER BY c.captured_at DESC) AS row_num
    FROM capture.road_capture c
), joined AS (
    SELECT c.capture_id, c.plate_text AS observed_plate, c.vin_fragment, c.captured_at, c.camera_id,
           r.registration_id, r.reg_no, r.vin AS registered_vin, r.owner_name, r.registration_date,
           r.make, r.model, r.color, r.registration_status, p.policy_id, p.valid_until,
           p.policy_status, p.insurer_name, s.case_id, s.incident_type, s.case_status
    FROM latest_capture c
    LEFT JOIN registry.vehicle_registration r ON REPLACE(REPLACE(UPPER(c.plate_text), '-', ''), ' ', '') = REPLACE(REPLACE(UPPER(r.reg_no), '-', ''), ' ', '')
    LEFT JOIN insurance.insurance_policy p ON REPLACE(REPLACE(UPPER(p.registration_no), '-', ''), ' ', '') = REPLACE(REPLACE(UPPER(r.reg_no), '-', ''), ' ', '')
    LEFT JOIN cases.theft_scrap_case s ON REPLACE(REPLACE(UPPER(s.plate), '-', ''), ' ', '') = REPLACE(REPLACE(UPPER(c.plate_text), '-', ''), ' ', '') AND s.case_status IN ('OPEN', 'AUTHORISED')
    WHERE c.row_num = 1
)
SELECT *,
    CASE WHEN incident_type = 'THEFT' AND case_status = 'OPEN' THEN 'STOP_AND_REPORT'
         WHEN incident_type = 'SCRAP' AND case_status = 'AUTHORISED' THEN 'STOP_AND_REPORT'
         WHEN registration_id IS NULL THEN 'UNRESOLVED_IDENTITY'
         WHEN registration_status <> 'VALID' THEN 'REGISTRATION_REVIEW'
         WHEN policy_id IS NULL THEN 'UNINSURED'
         WHEN policy_status <> 'ACTIVE' OR valid_until < date(captured_at) THEN 'INSURANCE_EXPIRED'
         ELSE 'CLEAR' END AS decision,
    CASE WHEN incident_type = 'THEFT' AND case_status = 'OPEN' THEN 'Open theft case'
         WHEN incident_type = 'SCRAP' AND case_status = 'AUTHORISED' THEN 'Vehicle was authorised for scrap/dismantling but is on the road'
         WHEN registration_id IS NULL THEN 'No authoritative registration match'
         WHEN registration_status <> 'VALID' THEN 'Registration is not valid'
         WHEN policy_id IS NULL THEN 'No insurance policy matched'
         WHEN policy_status <> 'ACTIVE' OR valid_until < date(captured_at) THEN 'Policy is not active on capture date'
         ELSE 'Valid registration and active insurance' END AS decision_reason
FROM joined
"""


def request_json(url: str, method: str = "GET", payload: object | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, method=method, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=4) as response:
            return json.loads(response.read())
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Source unavailable at {url}: {error}") from error


def remote_snapshot(alias: str) -> dict:
    return request_json(f"{SOURCE_URLS[alias]}/snapshot")


def identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def query_aliases(sql: str) -> set[str]:
    return {alias for alias in SOURCE_TABLES if re.search(rf"\b{re.escape(alias)}\s*\.", sql, re.IGNORECASE)}


def connection(aliases: set[str] | None = None) -> sqlite3.Connection:
    database = sqlite3.connect(":memory:")
    database.row_factory = sqlite3.Row
    selected_aliases = set(SOURCE_TABLES) if aliases is None else aliases
    for alias in SOURCE_TABLES:
        if alias not in selected_aliases:
            continue
        database.execute(f"ATTACH DATABASE ':memory:' AS {identifier(alias)}")
        snapshot = remote_snapshot(alias)
        definitions = []
        for column in snapshot["columns"]:
            definition = f"{identifier(column['name'])} {column.get('type') or 'TEXT'}"
            if column.get("pk"):
                definition += " PRIMARY KEY"
            definitions.append(definition)
        table = snapshot["table"]
        database.execute(f"CREATE TABLE {identifier(alias)}.{identifier(table)} ({', '.join(definitions)})")
        names = [column["name"] for column in snapshot["columns"]]
        if snapshot["rows"]:
            placeholders = ", ".join("?" for _ in names)
            database.executemany(f"INSERT INTO {identifier(alias)}.{identifier(table)} ({', '.join(identifier(name) for name in names)}) VALUES ({placeholders})", [tuple(row.get(name) for name in names) for row in snapshot["rows"]])
    return database


def query_rows(sql: str, parameters: tuple = (), aliases: set[str] | None = None) -> list[dict]:
    with connection(aliases) as database:
        return [dict(row) for row in database.execute(sql, parameters).fetchall()]


def safe_raw_query(sql: str) -> list[dict]:
    statement = sql.strip()
    first_word = statement.split(None, 1)[0].upper() if statement else ""
    blocked = ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "ATTACH", "DETACH", "PRAGMA", "REPLACE", "CREATE")
    if first_word not in ("SELECT", "WITH") or ";" in statement or any(word in statement.upper().split() for word in blocked):
        raise ValueError("Only one read-only SELECT or WITH query is allowed.")
    return query_rows(f"SELECT * FROM ({statement}) LIMIT 200", aliases=query_aliases(statement))


class Handler(BaseHTTPRequestHandler):
    def send_json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/detections":
                sql = f"{JOIN_QUERY} ORDER BY captured_at DESC"
                rows = query_rows(sql)
                audit_append({"operation": "READ", "source": "federated", "database": "all five source databases", "sql": "Vehicle decision query", "status": "SUCCESS", "rows": len(rows)})
                self.send_json(rows)
            elif parsed.path == "/api/vehicle":
                plate = parse_qs(parsed.query).get("plate", [""])[0]
                sql = f"SELECT * FROM ({JOIN_QUERY}) WHERE REPLACE(REPLACE(UPPER(observed_plate), '-', ''), ' ', '') = REPLACE(REPLACE(UPPER(?), '-', ''), ' ', '')"
                rows = query_rows(sql, (plate,))
                audit_append({"operation": "READ", "source": "federated", "database": "all five source databases", "sql": "Vehicle lookup", "status": "SUCCESS", "parameters": {"plate": plate}, "rows": len(rows)})
                self.send_json(rows[0] if rows else None, 200 if rows else 404)
            elif parsed.path == "/api/query":
                sql = parse_qs(parsed.query).get("sql", [""])[0]
                rows = safe_raw_query(sql)
                aliases = query_aliases(sql)
                audit_append({"operation": "READ", "source": "federated" if len(aliases) != 1 else next(iter(aliases)), "database": ", ".join(sorted(aliases)) if aliases else "none", "sql": sql, "status": "SUCCESS", "rows": len(rows)})
                self.send_json({"rows": rows})
            elif parsed.path == "/api/audit":
                self.send_json({"records": audit_read()[-200:]})
            elif parsed.path == "/api/schemas":
                schemas = {alias: remote_snapshot(alias)["columns"] for alias in SOURCE_TABLES}
                audit_append({"operation": "READ", "source": "federated", "database": "all five source databases", "sql": "Schema metadata lookup", "status": "SUCCESS"})
                self.send_json(schemas)
            elif parsed.path == "/api/source":
                alias = parse_qs(parsed.query).get("source", [""])[0]
                if alias not in SOURCE_TABLES:
                    self.send_json({"error": "Unknown source database."}, 400)
                    return
                snapshot = remote_snapshot(alias)
                audit_append({"operation": "READ", "source": alias, "database": SOURCE_TABLES[alias], "sql": "Source snapshot lookup", "status": "SUCCESS", "rows": len(snapshot["rows"])})
                self.send_json({"columns": snapshot["columns"], "rows": snapshot["rows"]})
            else:
                self.serve_static(parsed.path)
        except (ValueError, KeyError, sqlite3.Error, RuntimeError, json.JSONDecodeError, OSError) as error:
            self.send_json({"error": str(error)}, 502)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in ("/api/modify", "/api/audit/undo"):
            self.send_json({"error": "Unknown gateway endpoint."}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1_000_000:
                raise ValueError("Request body is missing or too large.")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Request body must be a JSON object.")
            if path == "/api/audit/undo":
                record_id = str(payload.get("id", ""))
                record = next((item for item in audit_read() if item.get("id") == record_id), None)
                if not record:
                    raise ValueError("Audit record was not found.")
                if record.get("operation") not in ("INSERT", "DELETE") or record.get("undone"):
                    raise ValueError("This audit record cannot be undone.")
                undo_sql = record.get("undo_sql")
                if not undo_sql:
                    raise ValueError("This change has no reversible operation.")
                result = request_json(f"{SOURCE_URLS[record['source']]}/execute", "POST", {"sql": undo_sql})
                audit_update(record_id, undone=True, undone_at=datetime.now(timezone.utc).isoformat())
                audit_append({"operation": "UNDO", "source": record["source"], "database": record["database"], "sql": undo_sql, "status": "SUCCESS", "changes": result.get("changes", 0), "undo_of": record_id})
                self.send_json({"changes": result.get("changes", 0), "message": "The change was undone."})
                return
            alias = payload.get("source")
            statement = str(payload.get("sql", "")).strip()
            expected_table = f"{alias}.{SOURCE_TABLES.get(alias, '')}"
            statement_without_semicolon = statement[:-1].strip() if statement.endswith(";") else statement
            first_word = statement_without_semicolon.split(None, 1)[0].upper() if statement_without_semicolon else ""
            if alias not in SOURCE_TABLES or first_word not in ("INSERT", "DELETE") or expected_table.lower() not in statement_without_semicolon.lower() or any(token in statement_without_semicolon.upper() for token in ("DROP ", "ALTER ", "ATTACH ", "PRAGMA ", "UPDATE ", ";")):
                raise ValueError("Only INSERT or DELETE on the selected source table is allowed.")
            remote_statement = re.sub(rf"\b{re.escape(expected_table)}\b", SOURCE_TABLES[alias], statement, count=1, flags=re.IGNORECASE)
            result = request_json(f"{SOURCE_URLS[alias]}/execute", "POST", {"sql": remote_statement})
            audit_append({"operation": first_word, "source": alias, "database": SOURCE_TABLES[alias], "sql": statement, "status": "SUCCESS", "changes": result.get("changes", 0), "undo_sql": result.get("undo_sql"), "undone": False})
            self.send_json(result)
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json({"error": str(error)}, 400)
        except RuntimeError as error:
            self.send_json({"error": str(error)}, 502)

    def serve_static(self, path: str) -> None:
        file = ROOT / ("index.html" if path == "/" else path.lstrip("/"))
        if not file.is_file() or file.parent != ROOT:
            self.send_error(404)
            return
        content_type = "text/html" if file.suffix == ".html" else "text/css" if file.suffix == ".css" else "text/javascript"
        body = file.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")


if __name__ == "__main__":
    print(f"Gateway running at http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
