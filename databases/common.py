"""Helpers shared by the five independent database modules.

Nothing here crosses database boundaries: each helper operates on ONE engine /
session. Cross-database integration happens only in the gateway via REST.
"""
import datetime
import os
import shutil
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy import inspect, text

from matching import normalize_plate, rank_candidate_record

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(BASE_DIR, "backups")


# ----------------------------------------------------------------------------
# Schema helpers
# ----------------------------------------------------------------------------
def object_exists(conn, name: str, obj_type: str = "table") -> bool:
    row = conn.execute(
        text("SELECT 1 FROM sqlite_master WHERE type=:t AND name=:n"), {"t": obj_type, "n": name}
    ).fetchone()
    return row is not None


def table_columns(conn, table: str) -> List[str]:
    return [row[1] for row in conn.execute(text(f"PRAGMA table_info('{table}')")).fetchall()]


def backup_database_file(db_file: str, reason: str) -> Optional[str]:
    """Copies a SQLite file into backups/<timestamp>_<reason>/ before a destructive step."""
    if not os.path.exists(db_file) or os.path.getsize(db_file) == 0:
        return None
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    target_dir = os.path.join(BACKUP_DIR, f"{stamp}_{reason}")
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, os.path.basename(db_file))
    shutil.copy2(db_file, target)
    return target


def describe_schema(engine) -> List[Dict[str, Any]]:
    """Tables, columns, primary keys, foreign keys, indexes and row counts of one database."""
    insp = inspect(engine)
    tables = []
    with engine.connect() as conn:
        for name in sorted(insp.get_table_names()):
            if name.startswith("sqlite_"):
                continue
            pk = insp.get_pk_constraint(name).get("constrained_columns", [])
            columns = [
                {"name": c["name"], "type": str(c["type"]), "nullable": bool(c["nullable"]), "primary_key": c["name"] in pk}
                for c in insp.get_columns(name)
            ]
            fks = [
                {"column": fk["constrained_columns"][0], "references_table": fk["referred_table"],
                 "references_column": fk["referred_columns"][0]}
                for fk in insp.get_foreign_keys(name)
            ]
            indexes = [{"name": i["name"], "columns": i["column_names"], "unique": bool(i["unique"])}
                       for i in insp.get_indexes(name)]
            count = conn.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar()
            tables.append({"table": name, "columns": columns, "primary_key": pk,
                           "foreign_keys": fks, "indexes": indexes, "row_count": count})
        views = [r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='view'")).fetchall()]
    return {"tables": tables, "views": views}


def foreign_key_violations(engine) -> List[Dict[str, Any]]:
    """Runs PRAGMA foreign_key_check (orphan detection) on one database."""
    with engine.connect() as conn:
        rows = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
    return [{"table": r[0], "rowid": r[1], "parent": r[2], "fk_index": r[3]} for r in rows]


def foreign_keys_enabled(engine) -> bool:
    with engine.connect() as conn:
        return bool(conn.execute(text("PRAGMA foreign_keys")).scalar())


def table_rows(engine, table: str, limit: int = 200) -> Dict[str, Any]:
    insp = inspect(engine)
    if table not in insp.get_table_names() and table not in insp.get_view_names():
        raise KeyError(table)
    with engine.connect() as conn:
        result = conn.execute(text(f'SELECT * FROM "{table}" LIMIT :limit'), {"limit": int(limit)})
        cols = list(result.keys())
        return {"table": table, "columns": cols, "rows": [dict(zip(cols, r)) for r in result.fetchall()]}


# ----------------------------------------------------------------------------
# Relationship-path helpers (record-level provenance of FK-PK traversal)
# ----------------------------------------------------------------------------
def path(from_table: str, from_id: Any, fk_column: str, to_table: str, to_id: Any, relation: str,
         direction: str = "forward") -> Dict[str, Any]:
    """forward: from_table.fk_column -> to_table.id ; reverse: to_table.fk_column -> from_table.id."""
    if direction == "forward":
        label = f"{from_table}#{from_id}.{fk_column} → {to_table}#{to_id}"
    else:
        label = f"{from_table}#{from_id} ← {to_table}#{to_id}.{fk_column}"
    return {"relation": relation, "from": f"{from_table}#{from_id}", "to": f"{to_table}#{to_id}",
            "fk_column": fk_column, "direction": direction, "label": label}


def row_dict(obj, exclude: Tuple[str, ...] = ()) -> Optional[Dict[str, Any]]:
    if obj is None:
        return None
    out = {}
    for col in obj.__table__.columns:
        if col.name in exclude:
            continue
        val = getattr(obj, col.name)
        if isinstance(val, (datetime.datetime, datetime.date)):
            val = val.isoformat()
        out[col.name] = val
    return out


# ----------------------------------------------------------------------------
# Generic local federated query (runs INSIDE one database service)
# ----------------------------------------------------------------------------
def run_local_federated_query(
    session,
    *,
    service_key: str,
    hub_model,
    hub_table: str,
    to_flat: Callable[[Any], Dict[str, Any]],
    expand: Callable[[Any, Any, Optional[List[str]]], Tuple[Dict[str, Any], List[Dict[str, Any]]]],
    request: Dict[str, Any],
    attribute_search: Optional[Callable[[Any, Dict[str, Any]], List[Any]]] = None,
    uses_context: bool = False,
) -> Dict[str, Any]:
    """Local subquery: fuzzy-match the plate against this DB's hub table, then expand
    each matched record through local FK-PK relationships.

    request keys: plate, mode ("lookup" | "similar"), context {make, model, colour, state},
    include [relation names] or None for all, max_candidates, min_similarity.
    """
    started = time.perf_counter()
    plate = normalize_plate(request.get("plate"))
    mode = request.get("mode", "lookup")
    include = request.get("include")
    context = {k: v for k, v in (request.get("context") or {}).items() if v} if uses_context else {}
    max_candidates = int(request.get("max_candidates") or (5 if mode == "similar" else 10))
    min_similarity = float(request.get("min_similarity") or (0.60 if mode == "similar" else 0.80))

    rows = session.query(hub_model).all()
    scored = []
    if plate:
        for row in rows:
            flat = to_flat(row)
            ranked = rank_candidate_record(plate, flat, service_key, flat.get("id", 0), context or None)
            if ranked["dl_similarity"] >= min_similarity or ranked["exact_match"] == 1.0:
                scored.append((ranked, row, flat))
        scored.sort(key=lambda x: (x[0]["exact_match"], x[0]["combined_score"], x[0]["dl_similarity"]), reverse=True)
    elif attribute_search and context:
        for row in attribute_search(session, context)[:max_candidates]:
            flat = to_flat(row)
            ranked = rank_candidate_record(flat.get("registration_number") or flat.get("plate_identifier") or "",
                                           flat, service_key, flat.get("id", 0), context)
            scored.append((ranked, row, flat))

    if mode == "lookup" and scored and scored[0][0]["exact_match"] == 1.0:
        # An exact plate hit exists: keep only records for that exact plate (e.g. several policies).
        scored = [s for s in scored if s[0]["exact_match"] == 1.0]
    scored = scored[:max_candidates]

    matches = []
    tables_touched = {hub_table}
    for ranked, row, flat in scored:
        related, paths = expand(session, row, include)
        for p in paths:
            tables_touched.add(p["to"].split("#")[0])
            tables_touched.add(p["from"].split("#")[0])
        match_info = {k: ranked[k] for k in (
            "exact_match", "plate_similarity", "edit_distance", "dl_similarity", "plate_score",
            "contextual_score", "combined_score", "confidence", "matching_method",
            "supporting_attributes", "conflicting_attributes")}
        matches.append({"record": flat, "record_id": flat.get("id"), "table": hub_table,
                        "match": match_info, "related": related, "relationship_paths": paths})

    return {
        "service": service_key,
        "query_plate": plate,
        "mode": mode,
        "include": include,
        "candidates_scanned": len(rows),
        "match_count": len(matches),
        "matches": matches,
        "tables_touched": sorted(tables_touched),
        "query_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def wanted(include: Optional[List[str]], relation: str) -> bool:
    return include is None or relation in include
