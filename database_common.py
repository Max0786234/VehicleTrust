"""Shared SQLite engine factory and direct (non-HTTP) audit helpers.

All engines created here enforce SQLite foreign keys (PRAGMA foreign_keys=ON is
per-connection in SQLite, so it is applied on every new connection).
"""
import datetime
import os
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _enable_sqlite_foreign_keys(dbapi_connection, _record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_db_engine(db_path: str):
    """Creates a SQLAlchemy engine for SQLite with multi-thread support and FK enforcement."""
    if not os.path.isabs(db_path):
        db_path = os.path.join(BASE_DIR, db_path)
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def get_session_factory(engine):
    """Returns a sessionmaker bound to the given engine."""
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


AUDIT_DB_PATH = "audit_log.db"


def __getattr__(name):
    # Backwards compatibility: `from database_common import AuditLog` keeps working.
    if name == "AuditLog":
        from databases.audit import AuditLog
        return AuditLog
    raise AttributeError(name)


def _audit_session(db_path: str) -> Session:
    from databases import initialize_database
    engine = initialize_database("audit_log", db_path, seed=False)
    return get_session_factory(engine)()


def log_cleansing_action(
    affected_source: str,
    record_id: int,
    field_name: str,
    old_value: Optional[str],
    new_value: Optional[str],
    reviewer_decision: str,
    reason: str = "",
    db_path: str = AUDIT_DB_PATH,
    **extra: Any,
) -> Dict[str, Any]:
    """Records an audit trail entry directly in a local audit database (no HTTP)."""
    from databases.audit import create_audit_entry
    session = _audit_session(db_path)
    try:
        entry = create_audit_entry(session, {
            "affected_source": affected_source, "record_id": record_id, "field_name": field_name,
            "old_value": old_value, "new_value": new_value, "reviewer_decision": reviewer_decision,
            "reason": reason, **extra,
        })
        return entry
    finally:
        session.close()


def get_audit_logs(limit: int = 100, source: Optional[str] = None, db_path: str = AUDIT_DB_PATH) -> List[Dict[str, Any]]:
    """Retrieves recent audit log entries directly from a local audit database."""
    from databases.audit import AuditLog
    session = _audit_session(db_path)
    try:
        query = session.query(AuditLog)
        if source:
            query = query.filter(AuditLog.affected_source == source)
        return [e.to_dict() for e in query.order_by(AuditLog.id.desc()).limit(limit).all()]
    finally:
        session.close()


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)
