"""Registration Authority database (registration_authority.db) — 5 relational tables.

    rto_offices 1──* rto_registrations 1──* registration_certificates
         1                  1
         │                  ├──* ownership_transfers   (office_id → rto_offices)
         └──────────────────┴──* registration_events   (office_id → rto_offices)

The RTO keeps its OWN make/model/colour as recorded at registration time; those
values intentionally stay independent of the Vehicle Registry (heterogeneous
sources are what Phase 2 conflict detection and cleansing work on).
"""
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import Column, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import declarative_base, relationship

from databases.common import object_exists, path, row_dict, table_columns, wanted
from matching import normalize_plate

Base = declarative_base()
SERVICE_KEY = "registration_authority"
HUB_TABLE = "rto_registrations"


class RTOOffice(Base):
    __tablename__ = "rto_offices"
    id = Column(Integer, primary_key=True, autoincrement=True)
    office_code = Column(String(16), unique=True, nullable=False, index=True)
    office_name = Column(String(96), nullable=False)
    city = Column(String(64), nullable=True)
    state = Column(String(32), nullable=False)
    registrations = relationship("RTORegistration", back_populates="office")


class RTORegistration(Base):
    __tablename__ = "rto_registrations"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    plate_identifier = Column(String(32), unique=True, index=True, nullable=False)
    office_id = Column(Integer, ForeignKey("rto_offices.id", ondelete="RESTRICT"), nullable=False, index=True)
    make = Column(String(64), nullable=False)
    model = Column(String(64), nullable=False)
    colour = Column(String(32), nullable=False)
    registration_date = Column(String(16), nullable=False)
    state = Column(String(32), nullable=False)
    authority_reference = Column(String(64), nullable=False)
    office = relationship("RTOOffice", back_populates="registrations")
    certificates = relationship("RegistrationCertificate", back_populates="registration", cascade="all, delete-orphan")
    transfers = relationship("OwnershipTransfer", back_populates="registration", cascade="all, delete-orphan",
                             order_by="OwnershipTransfer.transfer_date")
    events = relationship("RegistrationEvent", back_populates="registration", cascade="all, delete-orphan",
                          order_by="RegistrationEvent.event_date")


class RegistrationCertificate(Base):
    __tablename__ = "registration_certificates"
    id = Column(Integer, primary_key=True, autoincrement=True)
    registration_id = Column(Integer, ForeignKey("rto_registrations.id", ondelete="CASCADE"), nullable=False, index=True)
    rc_number = Column(String(32), unique=True, nullable=False, index=True)
    issue_date = Column(String(16), nullable=False)
    valid_until = Column(String(16), nullable=False)
    rc_status = Column(String(16), nullable=False, index=True)  # VALID, EXPIRED, SUSPENDED, CANCELLED
    registered_owner = Column(String(96), nullable=True)
    registration = relationship("RTORegistration", back_populates="certificates")


class OwnershipTransfer(Base):
    __tablename__ = "ownership_transfers"
    id = Column(Integer, primary_key=True, autoincrement=True)
    registration_id = Column(Integer, ForeignKey("rto_registrations.id", ondelete="CASCADE"), nullable=False, index=True)
    office_id = Column(Integer, ForeignKey("rto_offices.id", ondelete="RESTRICT"), nullable=False, index=True)
    transfer_date = Column(String(16), nullable=False)
    previous_owner = Column(String(96), nullable=False)
    new_owner = Column(String(96), nullable=False)
    transfer_reason = Column(String(48), nullable=True)
    registration = relationship("RTORegistration", back_populates="transfers")
    office = relationship("RTOOffice")


class RegistrationEvent(Base):
    __tablename__ = "registration_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    registration_id = Column(Integer, ForeignKey("rto_registrations.id", ondelete="CASCADE"), nullable=False, index=True)
    office_id = Column(Integer, ForeignKey("rto_offices.id", ondelete="RESTRICT"), nullable=False, index=True)
    event_date = Column(String(16), nullable=False)
    event_type = Column(String(32), nullable=False, index=True)
    description = Column(Text, nullable=True)
    registration = relationship("RTORegistration", back_populates="events")
    office = relationship("RTOOffice")


FLAT_FIELDS = ["plate_identifier", "make", "model", "colour", "registration_date", "state", "authority_reference"]


def to_flat(r: RTORegistration) -> Dict[str, Any]:
    return {
        "id": r.id, "plate_identifier": r.plate_identifier, "make": r.make, "model": r.model,
        "colour": r.colour, "registration_date": r.registration_date, "state": r.state,
        "authority_reference": r.authority_reference, "office_id": r.office_id,
        "office_code": r.office.office_code if r.office else None,
    }


def office_code_for_plate(plate: str) -> str:
    plate = normalize_plate(plate)
    if len(plate) >= 4 and plate[2:4] == "BH":
        return "MoRTH-BH"
    return plate[:4] if len(plate) >= 4 else plate


def get_or_create_office(session, plate: str, state: str) -> RTOOffice:
    code = office_code_for_plate(plate)
    office = session.query(RTOOffice).filter(RTOOffice.office_code == code).first()
    if not office:
        office = RTOOffice(office_code=code, office_name=f"RTO {code}", state=state or "Unknown")
        session.add(office)
        session.flush()
    return office


def apply_flat_update(session, reg: RTORegistration, updates: Dict[str, Any]) -> None:
    if updates.get("plate_identifier"):
        reg.plate_identifier = normalize_plate(updates["plate_identifier"])
    for field in ("make", "model", "colour", "registration_date", "state", "authority_reference"):
        if updates.get(field) is not None:
            setattr(reg, field, str(updates[field]).strip())
    if updates.get("office_id") is not None:
        if session.get(RTOOffice, int(updates["office_id"])) is None:
            raise ValueError(f"rto_offices#{updates['office_id']} does not exist (FK office_id)")
        reg.office_id = int(updates["office_id"])


RELATIONS = ["office", "certificates", "transfers", "events"]


def expand(session, r: RTORegistration, include: Optional[List[str]] = None) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    related: Dict[str, Any] = {}
    paths: List[Dict[str, Any]] = []
    if r.office and wanted(include, "office"):
        related["office"] = row_dict(r.office)
        paths.append(path("rto_registrations", r.id, "office_id", "rto_offices", r.office_id, "office"))
    if wanted(include, "certificates"):
        related["certificates"] = [row_dict(c) for c in r.certificates]
        for c in r.certificates:
            paths.append(path("rto_registrations", r.id, "registration_id", "registration_certificates", c.id, "certificates", "reverse"))
    if wanted(include, "transfers"):
        items = []
        for t in r.transfers:
            item = row_dict(t)
            item["office_code"] = t.office.office_code if t.office else None
            items.append(item)
            paths.append(path("rto_registrations", r.id, "registration_id", "ownership_transfers", t.id, "transfers", "reverse"))
            paths.append(path("ownership_transfers", t.id, "office_id", "rto_offices", t.office_id, "transfer_office"))
        related["transfers"] = items
    if wanted(include, "events"):
        items = []
        for e in r.events:
            item = row_dict(e)
            item["office_code"] = e.office.office_code if e.office else None
            items.append(item)
            paths.append(path("rto_registrations", r.id, "registration_id", "registration_events", e.id, "events", "reverse"))
        related["events"] = items
    return related, paths


def needs_migration(engine) -> bool:
    with engine.connect() as conn:
        return object_exists(conn, HUB_TABLE) and "office_id" not in table_columns(conn, HUB_TABLE)


def migrate(engine, session_factory) -> Dict[str, Any]:
    """Rebuilds rto_registrations with a mandatory FK to rto_offices (derived from the
    plate's state+RTO code). Registration ids are preserved."""
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE rto_registrations RENAME TO _legacy_rto_registrations"))
        legacy = conn.execute(text(
            "SELECT id, plate_identifier, make, model, colour, registration_date, state, authority_reference "
            "FROM _legacy_rto_registrations ORDER BY id")).fetchall()
        for (idx,) in conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='_legacy_rto_registrations' "
                "AND name NOT LIKE 'sqlite_%'")).fetchall():
            conn.execute(text(f'DROP INDEX "{idx}"'))
    Base.metadata.create_all(bind=engine)
    session = session_factory()
    try:
        for row in legacy:
            office = get_or_create_office(session, row.plate_identifier, row.state)
            session.add(RTORegistration(
                id=row.id, plate_identifier=normalize_plate(row.plate_identifier), office_id=office.id,
                make=row.make, model=row.model, colour=row.colour, registration_date=row.registration_date,
                state=row.state, authority_reference=row.authority_reference))
        session.commit()
        migrated = session.query(RTORegistration).count()
    finally:
        session.close()
    if migrated < len(legacy):
        raise RuntimeError(f"Registration migration verification failed ({migrated} < {len(legacy)})")
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE _legacy_rto_registrations"))
    return {"legacy_rows": len(legacy), "migrated_rows": migrated}


def post_create(engine) -> None:
    return None
