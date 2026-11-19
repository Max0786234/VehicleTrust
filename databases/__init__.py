"""The five independent VehicleTrust databases.

Each module owns one SQLite file: its SQLAlchemy models (4-6 FK-linked tables),
a migration from the Phase 2 single-table schema, and local FK-PK context
expansion used by federated queries.

initialize_database() is idempotent and non-destructive:
    1. back up the file if a legacy schema must be migrated
    2. migrate legacy rows (ids preserved, row counts verified)
    3. create any missing tables
    4. seed core rows only if the hub table is empty
    5. add related demonstration rows only where they are missing
    6. verify PRAGMA foreign_key_check reports no orphans
"""
from typing import Any, Dict, Optional

from database_common import get_db_engine, get_session_factory
from databases import audit, insurance, registration, registry, theft
from databases.common import backup_database_file, foreign_key_violations

MODULES = {
    "vehicle_registry": registry,
    "insurance_records": insurance,
    "registration_authority": registration,
    "theft_scrapping": theft,
    "audit_log": audit,
}

_LAST_REPORT: Dict[str, Dict[str, Any]] = {}


def initialize_database(key: str, db_file: Optional[str] = None, seed: bool = True, reset: bool = False,
                        verbose: bool = False):
    """Creates/migrates/seeds one database and returns its engine."""
    import config
    import seed_data

    module = MODULES[key]
    db_file = db_file or config.db_path(key)
    report: Dict[str, Any] = {"database": db_file, "backup": None, "migration": None, "seeded": {}}
    if reset:
        report["backup"] = backup_database_file(db_file, f"reset_{key}")
        import os
        if os.path.exists(db_file):
            os.remove(db_file)

    engine = get_db_engine(db_file)
    factory = get_session_factory(engine)
    if module.needs_migration(engine):
        report["backup"] = backup_database_file(db_file, f"pre_phase3_migration_{key}")
        report["migration"] = module.migrate(engine, factory)
    module.Base.metadata.create_all(bind=engine)
    module.post_create(engine)

    if seed:
        session = factory()
        try:
            report["seeded"] = seed_data.seed(key, session)
        finally:
            session.close()

    violations = foreign_key_violations(engine)
    if violations:
        raise RuntimeError(f"{key}: foreign key violations after initialization: {violations[:5]}")
    report["fk_violations"] = 0
    _LAST_REPORT[key] = report
    if verbose:
        mig = report["migration"]
        print(f"[DB] {key}: {db_file}")
        if report["backup"]:
            print(f"     backup   -> {report['backup']}")
        if mig:
            print(f"     migrated {mig['migrated_rows']}/{mig['legacy_rows']} legacy rows (ids preserved)")
        seeded = {k: v for k, v in report["seeded"].items() if v}
        print(f"     seeded   {seeded if seeded else 'nothing (already populated)'}; FK violations: 0")
    return engine


def last_report(key: str) -> Dict[str, Any]:
    return _LAST_REPORT.get(key, {})
