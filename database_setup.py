"""Create the five isolated, denormalised source databases used by the demo."""

from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent
DATABASE_DIR = ROOT / "source_databases"

SOURCES: dict[str, str] = {
    "road_capture": """
        CREATE TABLE IF NOT EXISTS road_capture (
            capture_id INTEGER PRIMARY KEY, plate_text TEXT NOT NULL, vin_fragment TEXT NOT NULL,
            observed_make TEXT NOT NULL, observed_model TEXT NOT NULL, observed_color TEXT NOT NULL,
            captured_at TEXT NOT NULL, camera_id TEXT NOT NULL
        );
        DELETE FROM road_capture;
        INSERT INTO road_capture VALUES
        (1,'AB-12-CD-3456','VIN-001','Toyota','Corolla','White','2026-09-16T08:30:00','CAM-NORTH-01'),
        (2,'XY 98 ZT 1111','VIN-002','Honda','Civic','Blue','2026-09-16T08:35:00','CAM-NORTH-01'),
        (3,'LM-44-QR-9000','VIN-003','Ford','Focus','Black','2026-09-16T08:40:00','CAM-EAST-02'),
        (4,'ST-77-UV-2222','VIN-004','Nissan','Micra','Red','2026-09-16T08:45:00','CAM-EAST-02'),
        (5,'UN-00-KN-4040','VIN-005','Kia','Rio','Silver','2026-09-16T08:50:00','CAM-SOUTH-03'),
        (6,'ZZ-99-XX-9999','VIN-404','Unknown','Unknown','Unknown','2026-09-16T08:55:00','CAM-SOUTH-03');
    """,
    "insurance": """
        CREATE TABLE IF NOT EXISTS insurance_policy (
            policy_id TEXT PRIMARY KEY, registration_no TEXT NOT NULL, policy_holder TEXT NOT NULL,
            vin TEXT NOT NULL, valid_from TEXT NOT NULL, valid_until TEXT NOT NULL,
            policy_status TEXT NOT NULL CHECK (policy_status IN ('ACTIVE', 'EXPIRED', 'CANCELLED')),
            insurer_name TEXT NOT NULL
        );
        DELETE FROM insurance_policy;
        INSERT INTO insurance_policy VALUES
        ('POL-1001','AB-12-CD-3456','A. Rahman','VIN-001-FULL','2026-01-01','2026-12-31','ACTIVE','Northstar Insurance'),
        ('POL-1002','XY-98-ZT-1111','B. Okafor','VIN-002-FULL','2025-08-01','2026-08-31','EXPIRED','Harbor Mutual'),
        ('POL-1003','LM44QR9000','C. Wei','VIN-003-FULL','2026-01-01','2026-12-31','ACTIVE','Northstar Insurance');
    """,
    "registry": """
        CREATE TABLE IF NOT EXISTS vehicle_registration (
            registration_id INTEGER PRIMARY KEY, reg_no TEXT NOT NULL, vin TEXT NOT NULL,
            owner_name TEXT NOT NULL, registration_date TEXT NOT NULL, make TEXT NOT NULL,
            model TEXT NOT NULL, color TEXT NOT NULL,
            registration_status TEXT NOT NULL CHECK (registration_status IN ('VALID', 'SUSPENDED', 'EXPIRED', 'CANCELLED'))
        );
        DELETE FROM vehicle_registration;
        INSERT INTO vehicle_registration VALUES
        (101,'AB12CD3456','VIN-001-FULL','Amina Rahman','2022-04-12','Toyota','Corolla','White','VALID'),
        (102,'XY98ZT1111','VIN-002-FULL','Ben Okafor','2021-07-30','Honda','Civic','Blue','VALID'),
        (103,'LM44QR9000','VIN-003-FULL','Chen Wei','2019-02-18','Ford','Focus','Black','VALID'),
        (104,'ST77UV2222','VIN-004-FULL','Diego Silva','2020-11-09','Nissan','Micra','Red','VALID'),
        (105,'UN00KN4040','VIN-005-FULL','Fatima Noor','2023-06-14','Kia','Rio','Silver','VALID');
    """,
    "cases": """
        CREATE TABLE IF NOT EXISTS theft_scrap_case (
            case_id TEXT PRIMARY KEY, plate TEXT NOT NULL, vin_last6 TEXT, incident_type TEXT NOT NULL,
            case_status TEXT NOT NULL CHECK (case_status IN ('OPEN', 'CLOSED', 'AUTHORISED')),
            reported_on TEXT NOT NULL, notes TEXT NOT NULL
        );
        DELETE FROM theft_scrap_case;
        INSERT INTO theft_scrap_case VALUES
        ('THEFT-77','ST-77-UV-2222','N-004','THEFT','OPEN','2026-09-10','Reported stolen by owner'),
        ('SCRAP-12','LM-44-QR-9000',NULL,'SCRAP','AUTHORISED','2025-04-02','Authorised dismantling completed');
    """,
    "ministry": """
        CREATE TABLE IF NOT EXISTS ministry_report (
            report_id INTEGER PRIMARY KEY AUTOINCREMENT, vehicle_key TEXT NOT NULL, report_type TEXT NOT NULL,
            severity TEXT NOT NULL CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
            reason TEXT NOT NULL, created_at TEXT NOT NULL,
            report_status TEXT NOT NULL CHECK (report_status IN ('OPEN', 'CLOSED', 'PENDING'))
        );
    """,
}


def initialise_sources() -> None:
    DATABASE_DIR.mkdir(exist_ok=True)
    for source, script in SOURCES.items():
        initialise_source(source)


def initialise_source(source: str) -> None:
    if source not in SOURCES:
        raise ValueError(f"Unknown source: {source}")
    DATABASE_DIR.mkdir(exist_ok=True)
    database_path = DATABASE_DIR / f"{source}.db"
    if database_path.exists():
        return
    with sqlite3.connect(database_path) as connection:
        connection.executescript(SOURCES[source])
