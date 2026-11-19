"""Builds the FastAPI app for one independent database service.

Every service exposes the same endpoint contract:

  GET  /health                    liveness + hub row count + table count
  GET  /records[?query=PLATE]     Phase 2 flat records (CRUD kept backwards compatible)
  GET/POST/PUT/DELETE /records/{id}
  GET  /schema                    tables, columns, PK/FK, indexes, row counts
  GET  /tables/{table}?limit=     raw rows of one local table (DB inspection)
  GET  /integrity                 PRAGMA foreign_keys + foreign_key_check
  POST /federated/query           Phase 3 local subquery + FK-PK context discovery
"""
from typing import Any, Callable, Dict, Optional, Type

from fastapi import Body, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

import config
from database_common import get_session_factory
from databases import MODULES, initialize_database
from databases.common import (describe_schema, foreign_key_violations, foreign_keys_enabled,
                              run_local_federated_query, table_rows)
from matching import normalize_plate


def _dump(model: BaseModel, exclude_unset: bool = False) -> Dict[str, Any]:
    return model.model_dump(exclude_unset=exclude_unset)


def build_service_app(
    key: str,
    title: str,
    create_model: Type[BaseModel],
    update_model: Type[BaseModel],
    create_record: Callable[[Any, Dict[str, Any]], Any],
    plate_column: Optional[str],
    not_found_label: str,
    db_file: Optional[str] = None,
):
    module = MODULES[key]
    db_file = db_file or config.db_path(key)
    engine = initialize_database(key, db_file)
    SessionLocal = get_session_factory(engine)
    hub = getattr(module, {
        "vehicle_registry": "Vehicle", "insurance_records": "InsurancePolicy",
        "registration_authority": "RTORegistration", "theft_scrapping": "TheftScrappingRecord",
        "audit_log": "AuditLog"}[key])
    to_flat = module.to_flat if hasattr(module, "to_flat") else (lambda r: r.to_dict())

    app = FastAPI(title=title, version="3.0.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    app.state.engine = engine
    app.state.db_file = db_file

    def get_or_404(session, record_id: int):
        rec = session.get(hub, record_id)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"{not_found_label} {record_id} not found")
        return rec

    @app.get("/health")
    def health_check():
        session = SessionLocal()
        try:
            return {"status": "ok", "service": key, "port": config.service_port(key), "database": db_file,
                    "record_count": session.query(hub).count(), "table_count": len(module.Base.metadata.tables),
                    "machine": config.SERVICES[key]["machine"]}
        finally:
            session.close()

    @app.get("/records")
    def get_records(query: Optional[str] = None, source: Optional[str] = None, limit: int = 1000):
        session = SessionLocal()
        try:
            q = session.query(hub)
            if query and plate_column:
                q = q.filter(getattr(hub, plate_column).ilike(f"%{normalize_plate(query)}%"))
            if key == "audit_log":
                if source:
                    q = q.filter(hub.affected_source == source)
                q = q.order_by(hub.id.desc())
            return [to_flat(r) for r in q.limit(limit).all()]
        finally:
            session.close()

    @app.get("/records/{record_id}")
    def get_record(record_id: int):
        session = SessionLocal()
        try:
            return to_flat(get_or_404(session, record_id))
        finally:
            session.close()

    @app.post("/records", status_code=status.HTTP_201_CREATED)
    def create(data: create_model):  # type: ignore[valid-type]
        session = SessionLocal()
        try:
            rec = create_record(session, _dump(data))
            if isinstance(rec, dict):
                return rec
            session.commit()
            session.refresh(rec)
            return to_flat(rec)
        except ValueError as exc:
            session.rollback()
            raise HTTPException(status_code=400, detail=str(exc))
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(status_code=400, detail=f"Integrity constraint failed: {exc.orig}")
        finally:
            session.close()

    if hasattr(module, "apply_flat_update"):
        @app.put("/records/{record_id}")
        def update(record_id: int, data: update_model):  # type: ignore[valid-type]
            session = SessionLocal()
            try:
                rec = get_or_404(session, record_id)
                updates = {k: (v.strip() if isinstance(v, str) else v)
                           for k, v in _dump(data, exclude_unset=True).items() if v is not None}
                module.apply_flat_update(session, rec, updates)
                session.commit()
                session.refresh(rec)
                return to_flat(rec)
            except ValueError as exc:
                session.rollback()
                raise HTTPException(status_code=400, detail=str(exc))
            except IntegrityError as exc:
                session.rollback()
                raise HTTPException(status_code=400, detail=f"Integrity constraint failed: {exc.orig}")
            finally:
                session.close()

        @app.delete("/records/{record_id}")
        def delete(record_id: int):
            session = SessionLocal()
            try:
                rec = get_or_404(session, record_id)
                session.delete(rec)
                session.commit()
                return {"deleted": True, "id": record_id, "service": key}
            except IntegrityError as exc:
                session.rollback()
                raise HTTPException(status_code=409, detail=f"Record is still referenced: {exc.orig}")
            finally:
                session.close()

    @app.get("/schema")
    def schema():
        info = describe_schema(engine)
        return {"service": key, "database": db_file, **info}

    @app.get("/tables/{table}")
    def rows(table: str, limit: int = 100):
        try:
            return table_rows(engine, table, min(limit, 500))
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Table {table} not found in {key}")

    @app.get("/integrity")
    def integrity():
        violations = foreign_key_violations(engine)
        return {"service": key, "foreign_keys_enabled": foreign_keys_enabled(engine),
                "violations": violations, "ok": not violations}

    @app.post("/federated/query")
    def federated_query(request: Dict[str, Any] = Body(...)):
        session = SessionLocal()
        try:
            if key == "audit_log":
                return module.run_audit_query(session, request)
            return run_local_federated_query(
                session, service_key=key, hub_model=hub, hub_table=module.HUB_TABLE, to_flat=to_flat,
                expand=module.expand, request=request,
                attribute_search=getattr(module, "attribute_search", None),
                uses_context=key in ("vehicle_registry", "registration_authority"),
            )
        finally:
            session.close()

    return app
