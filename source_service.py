"""Run one isolated source database as a small HTTP service."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from database_setup import DATABASE_DIR, SOURCES, initialise_source

SOURCE_TABLES = {"capture": "road_capture", "insurance": "insurance_policy", "registry": "vehicle_registration", "cases": "theft_scrap_case", "ministry": "ministry_report"}
SOURCE_ALIASES = {"capture": "road_capture", "insurance": "insurance", "registry": "registry", "cases": "cases", "ministry": "ministry"}


def identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def sql_value(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def insert_statement(table: str, columns: list[str], row: dict) -> str:
    names = ", ".join(identifier(column) for column in columns)
    values = ", ".join(sql_value(row.get(column)) for column in columns)
    return f"INSERT INTO {identifier(table)} ({names}) VALUES ({values})"


def primary_key_column(database: sqlite3.Connection, table: str) -> str:
    for row in database.execute(f"PRAGMA table_info({identifier(table)})").fetchall():
        if row[5]:
            return row[1]
    raise ValueError("The source table has no primary key for undo.")


def snapshot(source: str) -> dict:
    table = SOURCES[source].split("CREATE TABLE IF NOT EXISTS ", 1)[1].split(" (", 1)[0]
    with sqlite3.connect(DATABASE_DIR / f"{source}.db") as database:
        database.row_factory = sqlite3.Row
        columns = [dict(row) for row in database.execute(f"PRAGMA table_info({identifier(table)})").fetchall()]
        rows = [dict(row) for row in database.execute(f"SELECT * FROM {identifier(table)} LIMIT 500").fetchall()]
    return {"source": source, "table": table, "columns": columns, "rows": rows}


class SourceHandler(BaseHTTPRequestHandler):
    source = ""

    def send_json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        try:
            path = urlparse(self.path).path
            if path not in ("/snapshot", "/schema", "/rows", "/health"):
                self.send_json({"error": "Unknown source endpoint."}, 404)
                return
            current = snapshot(self.source)
            if path == "/schema":
                self.send_json({"source": self.source, "table": current["table"], "columns": current["columns"]})
            elif path == "/rows":
                self.send_json({"source": self.source, "table": current["table"], "rows": current["rows"]})
            elif path == "/health":
                self.send_json({"source": self.source, "status": "online"})
            else:
                self.send_json(current)
        except (KeyError, sqlite3.Error, OSError) as error:
            self.send_json({"error": f"Source database unavailable: {error}"}, 503)

    def do_POST(self) -> None:
        if self.path != "/execute":
            self.send_json({"error": "Unknown source endpoint."}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1_000_000:
                raise ValueError("Request body is missing or too large.")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Request body must be a JSON object.")
            statement = str(payload.get("sql", "")).strip()
            table = snapshot(self.source)["table"]
            statement_without_semicolon = statement[:-1].strip() if statement.endswith(";") else statement
            first_word = statement_without_semicolon.split(None, 1)[0].upper() if statement_without_semicolon else ""
            if first_word not in ("INSERT", "DELETE") or not re.search(rf"\b{re.escape(table)}\b", statement_without_semicolon, re.IGNORECASE) or any(token in statement_without_semicolon.upper() for token in ("DROP ", "ALTER ", "ATTACH ", "PRAGMA ", "UPDATE ", ";")):
                raise ValueError("Only INSERT or DELETE on this source table is allowed.")
            with sqlite3.connect(DATABASE_DIR / f"{self.source}.db") as database:
                database.row_factory = sqlite3.Row
                before = [dict(row) for row in database.execute(f"SELECT * FROM {identifier(table)}").fetchall()]
                columns = [row[1] for row in database.execute(f"PRAGMA table_info({identifier(table)})").fetchall()]
                if first_word == "INSERT":
                    result = database.execute(statement_without_semicolon + " RETURNING *")
                    changed_rows = [dict(row) for row in result.fetchall()]
                    primary_key = primary_key_column(database, table)
                    undo_sql = "\n".join(f"DELETE FROM {identifier(table)} WHERE {identifier(primary_key)} = {sql_value(item[primary_key])};" for item in changed_rows) if changed_rows else None
                else:
                    result = database.execute(statement_without_semicolon)
                    after = [dict(row) for row in database.execute(f"SELECT * FROM {identifier(table)}").fetchall()]
                    removed = [row for row in before if row not in after]
                    undo_sql = "\n".join(insert_statement(table, columns, row) + ";" for row in removed) if removed else None
                self.send_json({"changes": len(changed_rows) if first_word == "INSERT" else result.rowcount, "source": self.source, "undo_sql": undo_sql})
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json({"error": str(error)}, 400)
        except (sqlite3.Error, OSError) as error:
            self.send_json({"error": f"Database operation failed: {error}"}, 409)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[{self.source}] {self.address_string()} - {format % args}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=sorted(SOURCE_ALIASES), required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    source = SOURCE_ALIASES[args.source]
    initialise_source(source)
    handler = type("ConfiguredSourceHandler", (SourceHandler,), {"source": source})
    print(f"Source {args.source} ({source}.db) running on http://{args.host}:{args.port}")
    ThreadingHTTPServer((args.host, args.port), handler).serve_forever()


if __name__ == "__main__":
    main()