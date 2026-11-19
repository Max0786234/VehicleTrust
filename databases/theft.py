"""Theft & Scrapping database (theft_scrapping.db) — 6 relational tables.

    theft_scrapping_records (one status row per plate, Phase 2 table — unchanged columns)
        1──* theft_reports *──1 police_stations
                 1──* investigation_details
                 1──* recovery_records *──1 police_stations
        1──* scrapping_records
"""
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.orm import declarative_base, relationship

from databases.common import path, row_dict, wanted
from matching import normalize_plate

Base = declarative_base()
SERVICE_KEY = "theft_scrapping"
HUB_TABLE = "theft_scrapping_records"


class TheftScrappingRecord(Base):
    __tablename__ = "theft_scrapping_records"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    reported_plate = Column(String(32), unique=True, index=True, nullable=False)
    theft_status = Column(String(32), nullable=False)
    report_date = Column(String(16), nullable=False)
    scrapping_status = Column(String(32), nullable=False)
    theft_reports = relationship("TheftReport", back_populates="vehicle_record", cascade="all, delete-orphan")
    scrapping_records = relationship("ScrappingRecord", back_populates="vehicle_record", cascade="all, delete-orphan")


class PoliceStation(Base):
    __tablename__ = "police_stations"
    id = Column(Integer, primary_key=True, autoincrement=True)
    station_code = Column(String(16), unique=True, nullable=False, index=True)
    station_name = Column(String(96), nullable=False)
    city = Column(String(64), nullable=True)
    state = Column(String(32), nullable=False)


class TheftReport(Base):
    __tablename__ = "theft_reports"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vehicle_record_id = Column(Integer, ForeignKey("theft_scrapping_records.id", ondelete="CASCADE"), nullable=False, index=True)
    station_id = Column(Integer, ForeignKey("police_stations.id", ondelete="RESTRICT"), nullable=False, index=True)
    fir_number = Column(String(32), unique=True, nullable=False, index=True)
    report_date = Column(String(16), nullable=False)
    incident_location = Column(String(128), nullable=True)
    report_status = Column(String(16), nullable=False)  # OPEN, RECOVERED, CLOSED
    description = Column(Text, nullable=True)
    vehicle_record = relationship("TheftScrappingRecord", back_populates="theft_reports")
    station = relationship("PoliceStation", foreign_keys=[station_id])
    investigations = relationship("InvestigationDetail", back_populates="report", cascade="all, delete-orphan")
    recoveries = relationship("RecoveryRecord", back_populates="report", cascade="all, delete-orphan")


class InvestigationDetail(Base):
    __tablename__ = "investigation_details"
    id = Column(Integer, primary_key=True, autoincrement=True)
    theft_report_id = Column(Integer, ForeignKey("theft_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    investigating_officer = Column(String(96), nullable=False)
    investigation_status = Column(String(24), nullable=False)
    last_updated = Column(String(16), nullable=False)
    notes = Column(Text, nullable=True)
    report = relationship("TheftReport", back_populates="investigations")


class RecoveryRecord(Base):
    __tablename__ = "recovery_records"
    id = Column(Integer, primary_key=True, autoincrement=True)
    theft_report_id = Column(Integer, ForeignKey("theft_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    station_id = Column(Integer, ForeignKey("police_stations.id", ondelete="RESTRICT"), nullable=False, index=True)
    recovery_date = Column(String(16), nullable=False)
    recovery_location = Column(String(128), nullable=True)
    vehicle_condition = Column(String(48), nullable=True)
    report = relationship("TheftReport", back_populates="recoveries")
    station = relationship("PoliceStation")


class ScrappingRecord(Base):
    __tablename__ = "scrapping_records"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vehicle_record_id = Column(Integer, ForeignKey("theft_scrapping_records.id", ondelete="CASCADE"), nullable=False, index=True)
    certificate_number = Column(String(32), unique=True, nullable=True)
    facility_name = Column(String(96), nullable=False)
    application_date = Column(String(16), nullable=False)
    scrap_date = Column(String(16), nullable=True)
    scrap_status = Column(String(24), nullable=False)  # SCRAPPED, PENDING_SCRAP
    vehicle_record = relationship("TheftScrappingRecord", back_populates="scrapping_records")


FLAT_FIELDS = ["reported_plate", "theft_status", "report_date", "scrapping_status"]


def to_flat(r: TheftScrappingRecord) -> Dict[str, Any]:
    return {"id": r.id, "reported_plate": r.reported_plate, "theft_status": r.theft_status,
            "report_date": r.report_date, "scrapping_status": r.scrapping_status}


def apply_flat_update(session, rec: TheftScrappingRecord, updates: Dict[str, Any]) -> None:
    if updates.get("reported_plate"):
        rec.reported_plate = normalize_plate(updates["reported_plate"])
    if updates.get("report_date") is not None:
        rec.report_date = str(updates["report_date"]).strip()
    for field in ("theft_status", "scrapping_status"):
        if updates.get(field):
            setattr(rec, field, str(updates[field]).strip().upper())


RELATIONS = ["theft_reports", "investigations", "recoveries", "scrapping"]


def expand(session, r: TheftScrappingRecord, include: Optional[List[str]] = None) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    related: Dict[str, Any] = {}
    paths: List[Dict[str, Any]] = []
    want_reports = any(wanted(include, rel) for rel in ("theft_reports", "investigations", "recoveries"))
    if want_reports:
        reports = []
        for t in r.theft_reports:
            item = row_dict(t)
            item["station"] = row_dict(t.station)
            paths.append(path("theft_scrapping_records", r.id, "vehicle_record_id", "theft_reports", t.id, "theft_reports", "reverse"))
            paths.append(path("theft_reports", t.id, "station_id", "police_stations", t.station_id, "reporting_station"))
            if wanted(include, "investigations"):
                item["investigations"] = [row_dict(i) for i in t.investigations]
                for i in t.investigations:
                    paths.append(path("theft_reports", t.id, "theft_report_id", "investigation_details", i.id, "investigations", "reverse"))
            if wanted(include, "recoveries"):
                recs = []
                for rc in t.recoveries:
                    d = row_dict(rc)
                    d["station"] = row_dict(rc.station)
                    recs.append(d)
                    paths.append(path("theft_reports", t.id, "theft_report_id", "recovery_records", rc.id, "recoveries", "reverse"))
                    paths.append(path("recovery_records", rc.id, "station_id", "police_stations", rc.station_id, "recovery_station"))
                item["recoveries"] = recs
            reports.append(item)
        related["theft_reports"] = reports
    if wanted(include, "scrapping"):
        related["scrapping_records"] = [row_dict(s) for s in r.scrapping_records]
        for s in r.scrapping_records:
            paths.append(path("theft_scrapping_records", r.id, "vehicle_record_id", "scrapping_records", s.id, "scrapping", "reverse"))
    return related, paths


def needs_migration(engine) -> bool:
    return False  # hub table columns are unchanged; new tables are added by create_all


def migrate(engine, session_factory) -> Dict[str, Any]:
    return {"legacy_rows": 0, "migrated_rows": 0}


def post_create(engine) -> None:
    return None
