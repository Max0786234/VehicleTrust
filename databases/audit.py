"""Cleansing Audit Log database (audit_log.db) — 5 relational tables.

    reviewers 1──* audit_sessions 1──* cleansing_audit_log *──1 reviewers
                                            1
                             ┌──────────────┴──────────────┐
                             *                             *
                      audit_evidence               data_change_history

`affected_source` + `record_id` (+ `vehicle_plate`) identify the audited record in
another database; those are API-level identifiers, not SQLite FKs.
"""
import datetime
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, or_, text
from sqlalchemy.orm import declarative_base, relationship

from databases.common import object_exists, path, row_dict, table_columns, wanted
from matching import normalize_plate

Base = declarative_base()
SERVICE_KEY = "audit_log"
HUB_TABLE = "cleansing_audit_log"
DEFAULT_REVIEWER = "dashboard-reviewer"


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


class Reviewer(Base):
    __tablename__ = "reviewers"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(48), unique=True, nullable=False, index=True)
    full_name = Column(String(96), nullable=False)
    role = Column(String(32), nullable=False, default="DATA_STEWARD")


class AuditSession(Base):
    __tablename__ = "audit_sessions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_code = Column(String(48), unique=True, nullable=False, index=True)
    reviewer_id = Column(Integer, ForeignKey("reviewers.id", ondelete="RESTRICT"), nullable=False, index=True)
    started_at = Column(DateTime, default=_now, nullable=False)
    client = Column(String(48), nullable=True)
    query_plate = Column(String(32), nullable=True)
    reviewer = relationship("Reviewer")


class AuditLog(Base):
    """Audit log model tracking every data cleansing and review decision (Phase 2 table, extended)."""
    __tablename__ = "cleansing_audit_log"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    affected_source = Column(String(64), nullable=False, index=True)
    record_id = Column(Integer, nullable=False)
    vehicle_plate = Column(String(32), nullable=True, index=True)
    field_name = Column(String(64), nullable=False)
    old_value = Column(String(255), nullable=True)
    new_value = Column(String(255), nullable=True)
    reviewer_decision = Column(String(32), nullable=False)  # ACCEPTED, REJECTED, UNRESOLVED, STALE, FAILED
    timestamp = Column(DateTime, default=_now, nullable=False)
    reason = Column(Text, nullable=True)
    reviewer_id = Column(Integer, ForeignKey("reviewers.id", ondelete="RESTRICT"), nullable=True, index=True)
    session_id = Column(Integer, ForeignKey("audit_sessions.id", ondelete="RESTRICT"), nullable=True, index=True)
    reviewer = relationship("Reviewer")
    session = relationship("AuditSession")
    evidence = relationship("AuditEvidence", back_populates="audit_entry", cascade="all, delete-orphan")
    changes = relationship("DataChangeHistory", back_populates="audit_entry", cascade="all, delete-orphan")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "affected_source": self.affected_source,
            "record_id": self.record_id,
            "vehicle_plate": self.vehicle_plate,
            "field_name": self.field_name,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "reviewer_decision": self.reviewer_decision,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "reason": self.reason or "",
            "reviewer": self.reviewer.username if self.reviewer else None,
            "session_code": self.session.session_code if self.session else None,
        }


class AuditEvidence(Base):
    __tablename__ = "audit_evidence"
    id = Column(Integer, primary_key=True, autoincrement=True)
    audit_log_id = Column(Integer, ForeignKey("cleansing_audit_log.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_source = Column(String(64), nullable=False)
    evidence_record_id = Column(Integer, nullable=True)
    evidence_field = Column(String(64), nullable=True)
    evidence_value = Column(String(255), nullable=True)
    plate_similarity = Column(Float, nullable=True)
    description = Column(Text, nullable=True)
    audit_entry = relationship("AuditLog", back_populates="evidence")


class DataChangeHistory(Base):
    __tablename__ = "data_change_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    audit_log_id = Column(Integer, ForeignKey("cleansing_audit_log.id", ondelete="CASCADE"), nullable=False, index=True)
    target_source = Column(String(64), nullable=False)
    target_record_id = Column(Integer, nullable=False)
    field_name = Column(String(64), nullable=False)
    value_before = Column(String(255), nullable=True)
    value_after = Column(String(255), nullable=True)
    applied_at = Column(DateTime, default=_now, nullable=False)
    audit_entry = relationship("AuditLog", back_populates="changes")


def get_or_create_reviewer(session, username: Optional[str]) -> Reviewer:
    username = (username or DEFAULT_REVIEWER).strip()
    reviewer = session.query(Reviewer).filter(Reviewer.username == username).first()
    if not reviewer:
        reviewer = Reviewer(username=username, full_name=username.replace("-", " ").title(), role="DATA_STEWARD")
        session.add(reviewer)
        session.flush()
    return reviewer


def create_audit_entry(session, data: Dict[str, Any]) -> Dict[str, Any]:
    """Creates the audit row plus its evidence / change-history child rows in one transaction."""
    reviewer = get_or_create_reviewer(session, data.get("reviewer"))
    session_code = data.get("session_code") or f"SES-{datetime.date.today():%Y%m%d}-{reviewer.username}"
    audit_session = session.query(AuditSession).filter(AuditSession.session_code == session_code).first()
    if not audit_session:
        audit_session = AuditSession(session_code=session_code, reviewer_id=reviewer.id,
                                     client=data.get("client") or "gateway",
                                     query_plate=normalize_plate(data.get("vehicle_plate")) or None)
        session.add(audit_session)
        session.flush()
    entry = AuditLog(
        affected_source=data["affected_source"], record_id=int(data["record_id"]),
        vehicle_plate=normalize_plate(data.get("vehicle_plate")) or None,
        field_name=data["field_name"],
        old_value=None if data.get("old_value") is None else str(data["old_value"]),
        new_value=None if data.get("new_value") is None else str(data["new_value"]),
        reviewer_decision=str(data["reviewer_decision"]).upper(), timestamp=_now(),
        reason=data.get("reason") or "", reviewer_id=reviewer.id, session_id=audit_session.id,
    )
    session.add(entry)
    session.flush()
    evidence = data.get("evidence")
    if evidence:
        session.add(AuditEvidence(
            audit_log_id=entry.id, evidence_source=evidence.get("source", "unknown"),
            evidence_record_id=evidence.get("record_id"), evidence_field=evidence.get("field"),
            evidence_value=None if evidence.get("value") is None else str(evidence.get("value")),
            plate_similarity=evidence.get("plate_similarity"), description=evidence.get("description")))
    if entry.reviewer_decision == "ACCEPTED" and entry.new_value is not None:
        session.add(DataChangeHistory(
            audit_log_id=entry.id, target_source=entry.affected_source, target_record_id=entry.record_id,
            field_name=entry.field_name, value_before=entry.old_value, value_after=entry.new_value))
    session.commit()
    session.refresh(entry)
    return entry.to_dict()


RELATIONS = ["reviewer", "session", "evidence", "changes"]


def expand(session, a: AuditLog, include: Optional[List[str]] = None) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    related: Dict[str, Any] = {}
    paths: List[Dict[str, Any]] = []
    if a.reviewer and wanted(include, "reviewer"):
        related["reviewer"] = row_dict(a.reviewer)
        paths.append(path("cleansing_audit_log", a.id, "reviewer_id", "reviewers", a.reviewer_id, "reviewer"))
    if a.session and wanted(include, "session"):
        related["session"] = row_dict(a.session)
        paths.append(path("cleansing_audit_log", a.id, "session_id", "audit_sessions", a.session_id, "session"))
    if wanted(include, "evidence"):
        related["evidence"] = [row_dict(e) for e in a.evidence]
        for e in a.evidence:
            paths.append(path("cleansing_audit_log", a.id, "audit_log_id", "audit_evidence", e.id, "evidence", "reverse"))
    if wanted(include, "changes"):
        related["changes"] = [row_dict(c) for c in a.changes]
        for c in a.changes:
            paths.append(path("cleansing_audit_log", a.id, "audit_log_id", "data_change_history", c.id, "changes", "reverse"))
    return related, paths


def run_audit_query(session, request: Dict[str, Any]) -> Dict[str, Any]:
    """Audit subquery: finds audit rows for the record references discovered in the
    other databases (source, record_id) and/or the resolved plate, then expands FKs."""
    started = time.perf_counter()
    refs = request.get("record_refs") or []
    plate = normalize_plate(request.get("plate"))
    include = request.get("include")
    conditions = []
    for ref in refs:
        if ref.get("source") and ref.get("record_id") is not None:
            conditions.append((AuditLog.affected_source == ref["source"]) & (AuditLog.record_id == int(ref["record_id"])))
    if plate:
        conditions.append(AuditLog.vehicle_plate == plate)
    rows = []
    if conditions:
        rows = session.query(AuditLog).filter(or_(*conditions)).order_by(AuditLog.id.desc()).limit(50).all()
    matches = []
    for a in rows:
        related, paths = expand(session, a, include)
        matches.append({"record": a.to_dict(), "record_id": a.id, "table": HUB_TABLE,
                        "match": {"matched_by": "record_ref" if any(
                            r.get("source") == a.affected_source and r.get("record_id") == a.record_id for r in refs)
                            else "vehicle_plate", "combined_score": 1.0, "confidence": "HIGH"},
                        "related": related, "relationship_paths": paths})
    tables = {HUB_TABLE}
    for m in matches:
        for p in m["relationship_paths"]:
            tables.add(p["to"].split("#")[0])
    return {"service": SERVICE_KEY, "query_plate": plate, "mode": "lookup", "include": include,
            "record_refs": refs, "candidates_scanned": session.query(AuditLog).count(),
            "match_count": len(matches), "matches": matches, "tables_touched": sorted(tables),
            "query_ms": round((time.perf_counter() - started) * 1000, 2)}


def needs_migration(engine) -> bool:
    with engine.connect() as conn:
        return object_exists(conn, HUB_TABLE) and "reviewer_id" not in table_columns(conn, HUB_TABLE)


def migrate(engine, session_factory) -> Dict[str, Any]:
    """Rebuilds cleansing_audit_log with the new FK columns; existing entries keep their ids."""
    cols = "id, affected_source, record_id, field_name, old_value, new_value, reviewer_decision, timestamp, reason"
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE cleansing_audit_log RENAME TO _legacy_cleansing_audit_log"))
        for (idx,) in conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='_legacy_cleansing_audit_log' "
                "AND name NOT LIKE 'sqlite_%'")).fetchall():
            conn.execute(text(f'DROP INDEX "{idx}"'))
        legacy_count = conn.execute(text("SELECT COUNT(*) FROM _legacy_cleansing_audit_log")).scalar()
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text(f"INSERT INTO cleansing_audit_log ({cols}) SELECT {cols} FROM _legacy_cleansing_audit_log"))
        migrated = conn.execute(text("SELECT COUNT(*) FROM cleansing_audit_log")).scalar()
        if migrated < legacy_count:
            raise RuntimeError(f"Audit migration verification failed ({migrated} < {legacy_count})")
        conn.execute(text("DROP TABLE _legacy_cleansing_audit_log"))
    return {"legacy_rows": legacy_count, "migrated_rows": migrated}


def post_create(engine) -> None:
    return None


def new_session_code() -> str:
    return f"SES-{uuid.uuid4().hex[:10]}"
