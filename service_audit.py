"""Cleansing Audit Log service (port 8105, audit_log.db). Runs on machine-1.

Audit rows are append-only (no PUT/DELETE). POST /records accepts the Phase 2
fields plus optional reviewer, vehicle_plate, session_code and evidence.
"""
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

import config
from databases import audit as db
from databases.service_factory import build_service_app


class AuditEntryCreate(BaseModel):
    affected_source: str = Field(..., min_length=2, max_length=64)
    record_id: int
    field_name: str = Field(..., min_length=1, max_length=64)
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    reviewer_decision: str = Field(..., examples=["ACCEPTED", "REJECTED", "UNRESOLVED"])
    reason: Optional[str] = ""
    vehicle_plate: Optional[str] = None
    reviewer: Optional[str] = None
    session_code: Optional[str] = None
    evidence: Optional[Dict[str, Any]] = None


def create_record(session, data):
    return db.create_audit_entry(session, data)


app = build_service_app("audit_log", "Cleansing Audit Ledger Service", AuditEntryCreate, AuditEntryCreate,
                        create_record, "vehicle_plate", "Audit record")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.service_port("audit_log"))
